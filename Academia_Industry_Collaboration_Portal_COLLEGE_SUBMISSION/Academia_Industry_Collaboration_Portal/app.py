import os, json, math, random, secrets, smtplib, re
from email.message import EmailMessage
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
BASE = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Production-safe configuration. Set these in the hosting provider's Environment settings.
secret_key = os.getenv('SECRET_KEY', '').strip()
if not secret_key and os.getenv('FLASK_ENV', '').lower() == 'production':
    raise RuntimeError('SECRET_KEY must be set in production.')
app.config['SECRET_KEY'] = secret_key or 'dev-secret-change-me'

def normalize_database_url(value):
    value = (value or '').strip()
    # Render/Heroku may provide postgres://; SQLAlchemy needs an explicit driver.
    if value.startswith('postgres://'):
        return 'postgresql+psycopg://' + value[len('postgres://'):]
    if value.startswith('postgresql://'):
        return 'postgresql+psycopg://' + value[len('postgresql://'):]
    return value

database_url = normalize_database_url(os.getenv('DATABASE_URL'))
if not database_url:
    database_url = 'sqlite:///' + os.path.join(BASE, 'instance', 'portal.db')
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280,
}
# For hosted deployments, set UPLOAD_FOLDER to a persistent mounted disk or external storage path.
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', os.path.join(BASE, 'static', 'uploads'))
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
app.config['OTP_EXPIRE_MINUTES'] = int(os.getenv('OTP_EXPIRE_MINUTES', '10'))
app.config['OTP_MAX_ATTEMPTS'] = int(os.getenv('OTP_MAX_ATTEMPTS', '5'))
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(BASE, 'instance'), exist_ok=True)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@app.template_filter('fromjson')
def fromjson_filter(value):
    try:
        return json.loads(value)
    except Exception:
        return []

# ---------- Models ----------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(40), nullable=False, index=True)
    active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False)
    phone_verified = db.Column(db.Boolean, default=False)
    phone = db.Column(db.String(30))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('StudentProfile', backref='user', uselist=False, cascade='all, delete-orphan')
    faculty = db.relationship('FacultyProfile', backref='user', uselist=False, cascade='all, delete-orphan')
    company_user = db.relationship('CompanyUser', backref='user', uselist=False, cascade='all, delete-orphan')
    notifications = db.relationship('Notification', backref='user', cascade='all, delete-orphan')

class UserAvatar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('avatar', uselist=False, cascade='all, delete-orphan'))

class VerificationOTP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    channel = db.Column(db.String(20), nullable=False)  # email / phone
    destination = db.Column(db.String(180), nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, default=0)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('verification_otps', cascade='all, delete-orphan'))

class Institution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    city = db.Column(db.String(100))
    departments = db.relationship('Department', backref='institution', cascade='all, delete-orphan')

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    institution_id = db.Column(db.Integer, db.ForeignKey('institution.id'))

class Program(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=False)
    level = db.Column(db.String(80), default='Undergraduate')
    duration = db.Column(db.String(80))
    active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False)
    phone_verified = db.Column(db.Boolean, default=False)
    phone = db.Column(db.String(30))
    department = db.relationship('Department', backref=db.backref('programs', cascade='all, delete-orphan'))
    __table_args__ = (db.UniqueConstraint('department_id','name',name='uq_program_department_name'),)

class StudentProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    institution = db.Column(db.String(180)); department = db.Column(db.String(150)); program = db.Column(db.String(120))
    semester = db.Column(db.String(30)); graduation_year = db.Column(db.Integer); location = db.Column(db.String(100))
    phone = db.Column(db.String(40)); desired_role = db.Column(db.String(120)); bio = db.Column(db.Text)
    visibility = db.Column(db.Boolean, default=True); resume = db.Column(db.String(255))
    skills = db.relationship('StudentSkill', backref='student', cascade='all, delete-orphan')

class FacultyProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    institution = db.Column(db.String(180)); department = db.Column(db.String(150)); designation = db.Column(db.String(120))
    qualifications = db.Column(db.String(255)); experience = db.Column(db.String(80)); expertise = db.Column(db.Text); research = db.Column(db.Text)

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False); industry = db.Column(db.String(120)); website = db.Column(db.String(255))
    email = db.Column(db.String(180)); location = db.Column(db.String(120)); size = db.Column(db.String(80)); description = db.Column(db.Text)
    verification_status = db.Column(db.String(40), default='Pending')
    users = db.relationship('CompanyUser', backref='company', cascade='all, delete-orphan')
    skills = db.relationship('CompanySkill', backref='company', cascade='all, delete-orphan')
    opportunities = db.relationship('Opportunity', backref='company', cascade='all, delete-orphan')

class CompanyUser(db.Model):
    id = db.Column(db.Integer, primary_key=True); user_id = db.Column(db.Integer, db.ForeignKey('user.id')); company_id = db.Column(db.Integer, db.ForeignKey('company.id')); title = db.Column(db.String(120))

class Skill(db.Model):
    id = db.Column(db.Integer, primary_key=True); name = db.Column(db.String(120), unique=True, nullable=False); category = db.Column(db.String(80)); level = db.Column(db.String(40), default='Intermediate')

class AssessmentQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey('skill.id'), nullable=False)
    question = db.Column(db.Text, nullable=False)
    options_json = db.Column(db.Text, nullable=False)
    correct_index = db.Column(db.Integer, nullable=False)
    explanation = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    skill = db.relationship('Skill', backref=db.backref('assessment_questions', cascade='all, delete-orphan'))

class AssessmentAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey('skill.id'), nullable=False)
    total_questions = db.Column(db.Integer, default=0)
    correct_answers = db.Column(db.Integer, default=0)
    score_percent = db.Column(db.Float, default=0)
    level = db.Column(db.Integer, default=1)
    answers_json = db.Column(db.Text, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('StudentProfile', backref=db.backref('assessment_attempts', cascade='all, delete-orphan'))
    skill = db.relationship('Skill')

class StudentSkill(db.Model):
    id = db.Column(db.Integer, primary_key=True); student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id')); skill_id = db.Column(db.Integer, db.ForeignKey('skill.id')); level = db.Column(db.Integer, default=2); verified = db.Column(db.Boolean, default=False)
    skill = db.relationship('Skill')

class CompanySkill(db.Model):
    id = db.Column(db.Integer, primary_key=True); company_id = db.Column(db.Integer, db.ForeignKey('company.id')); skill_id = db.Column(db.Integer, db.ForeignKey('skill.id')); priority = db.Column(db.String(30), default='High'); level = db.Column(db.Integer, default=3)
    skill = db.relationship('Skill')

class CareerRole(db.Model):
    id = db.Column(db.Integer, primary_key=True); name = db.Column(db.String(150), unique=True); domain = db.Column(db.String(100)); description = db.Column(db.Text)
    skills = db.relationship('RoleSkill', backref='role', cascade='all, delete-orphan')

class RoleSkill(db.Model):
    id = db.Column(db.Integer, primary_key=True); role_id = db.Column(db.Integer, db.ForeignKey('career_role.id')); skill_id = db.Column(db.Integer, db.ForeignKey('skill.id')); required_level = db.Column(db.Integer, default=3)
    skill = db.relationship('Skill')

class Opportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True); company_id = db.Column(db.Integer, db.ForeignKey('company.id')); type = db.Column(db.String(40)); title = db.Column(db.String(180)); description = db.Column(db.Text)
    eligibility = db.Column(db.Text); openings = db.Column(db.Integer, default=1); location = db.Column(db.String(120)); mode = db.Column(db.String(40)); duration = db.Column(db.String(80)); compensation = db.Column(db.String(120)); deadline = db.Column(db.DateTime)
    status = db.Column(db.String(40), default='Submitted'); created_at = db.Column(db.DateTime, default=datetime.utcnow)
    skills = db.relationship('OpportunitySkill', backref='opportunity', cascade='all, delete-orphan'); applications = db.relationship('Application', backref='opportunity', cascade='all, delete-orphan')

class OpportunitySkill(db.Model):
    id = db.Column(db.Integer, primary_key=True); opportunity_id = db.Column(db.Integer, db.ForeignKey('opportunity.id')); skill_id = db.Column(db.Integer, db.ForeignKey('skill.id')); required_level = db.Column(db.Integer, default=3)
    skill = db.relationship('Skill')

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True); opportunity_id = db.Column(db.Integer, db.ForeignKey('opportunity.id')); student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id')); status = db.Column(db.String(40), default='Submitted'); match_score = db.Column(db.Float, default=0); created_at = db.Column(db.DateTime, default=datetime.utcnow); updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('StudentProfile'); history = db.relationship('ApplicationHistory', backref='application', cascade='all, delete-orphan')

class ApplicationHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True); application_id = db.Column(db.Integer, db.ForeignKey('application.id')); status = db.Column(db.String(40)); note = db.Column(db.Text); actor_id = db.Column(db.Integer); created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True); title = db.Column(db.String(180)); provider = db.Column(db.String(120)); level = db.Column(db.String(50)); duration = db.Column(db.String(50)); description = db.Column(db.Text); skill_id = db.Column(db.Integer, db.ForeignKey('skill.id'))
    skill = db.relationship('Skill')

class LearningProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True); student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id')); course_id = db.Column(db.Integer, db.ForeignKey('course.id')); progress = db.Column(db.Integer, default=0); completed = db.Column(db.Boolean, default=False)
    course = db.relationship('Course')

class LearningEnrollment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    resource_type = db.Column(db.String(30), nullable=False)  # course / fdp / training
    resource_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(40), default='Pending Verification')
    progress = db.Column(db.Integer, default=0)
    attendance_percent = db.Column(db.Integer, default=0)
    completed = db.Column(db.Boolean, default=False)
    verified_by = db.Column(db.Integer)
    verified_at = db.Column(db.DateTime)
    completion_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('StudentProfile')
    __table_args__ = (db.UniqueConstraint('student_id','resource_type','resource_id',name='uq_learning_enrollment'),)

class Certification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    name = db.Column(db.String(180), nullable=False)
    issuing_organization = db.Column(db.String(180), nullable=False)
    certificate_id = db.Column(db.String(180))
    issue_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    credential_url = db.Column(db.String(500))
    description = db.Column(db.Text)
    file_name = db.Column(db.String(255))
    verification_status = db.Column(db.String(40), default='Pending')
    verified_by = db.Column(db.Integer)
    verified_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('StudentProfile', backref=db.backref('certifications', cascade='all, delete-orphan'))

class PortfolioProject(db.Model):
    id = db.Column(db.Integer, primary_key=True); student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id')); title = db.Column(db.String(180)); description = db.Column(db.Text); link = db.Column(db.String(255))

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True); user_id = db.Column(db.Integer, db.ForeignKey('user.id')); title = db.Column(db.String(180)); body = db.Column(db.Text); kind = db.Column(db.String(50)); read = db.Column(db.Boolean, default=False); created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Guidance(db.Model):
    id = db.Column(db.Integer, primary_key=True); faculty_id = db.Column(db.Integer, db.ForeignKey('faculty_profile.id')); student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id')); note = db.Column(db.Text); action = db.Column(db.String(180)); created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True); title = db.Column(db.String(180)); event_type = db.Column(db.String(80)); event_date = db.Column(db.DateTime); location = db.Column(db.String(120)); description = db.Column(db.Text)

class Mentorship(db.Model):
    id = db.Column(db.Integer, primary_key=True); title = db.Column(db.String(180)); mentor = db.Column(db.String(120)); domain = db.Column(db.String(100)); seats = db.Column(db.Integer, default=10); status = db.Column(db.String(40), default='Open')

class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True); user_id = db.Column(db.Integer, db.ForeignKey('user.id')); category = db.Column(db.String(80)); subject = db.Column(db.String(180)); description = db.Column(db.Text); priority = db.Column(db.String(30), default='Normal'); status = db.Column(db.String(40), default='Open'); created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True); key = db.Column(db.String(80), unique=True); value = db.Column(db.String(255))

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True); actor_id = db.Column(db.Integer); action = db.Column(db.String(180)); target = db.Column(db.String(180)); detail = db.Column(db.Text); created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ModuleRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String(80), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))
    status = db.Column(db.String(50), default='Active')
    location = db.Column(db.String(120))
    due_date = db.Column(db.DateTime)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner = db.relationship('User', foreign_keys=[owner_id])

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(180), nullable=False)
    body = db.Column(db.Text, nullable=False)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])

class SavedOpportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    opportunity_id = db.Column(db.Integer, db.ForeignKey('opportunity.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('student_id','opportunity_id',name='uq_saved_opportunity'),)
    opportunity = db.relationship('Opportunity')

class MentorshipRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mentorship_id = db.Column(db.Integer, db.ForeignKey('mentorship.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    status = db.Column(db.String(40), default='Pending')
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    mentorship = db.relationship('Mentorship')
    student = db.relationship('StudentProfile')

class CollaborationRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('module_record.id'))
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(40), default='Pending')
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    record = db.relationship('ModuleRecord')
    requester = db.relationship('User', foreign_keys=[requester_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])

@login_manager.user_loader
def load_user(uid): return db.session.get(User, int(uid))

# ---------- Auth / helpers ----------
ROLE_HOME = {'Student':'student_dashboard','Faculty':'faculty_dashboard','Industry':'industry_dashboard','Institution Admin':'admin_dashboard','Platform Admin':'admin_dashboard','Super Admin':'admin_dashboard'}

def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        @login_required
        def wrapped(*a, **kw):
            if current_user.role not in roles: abort(403)
            return fn(*a, **kw)
        return wrapped
    return deco

def notify(user_id, title, body, kind='system'):
    db.session.add(Notification(user_id=user_id, title=title, body=body, kind=kind))

def audit(action, target='', detail=''):
    db.session.add(AuditLog(actor_id=current_user.id if current_user.is_authenticated else None, action=action, target=target, detail=detail))

def student_match(student, opp):
    ss = {x.skill_id:x.level for x in student.skills}
    req = opp.skills
    if not req: return 60.0, []
    scores=[]; explanations=[]
    for r in req:
        have=ss.get(r.skill_id,0); pct=min(1, have/max(1,r.required_level)); scores.append(pct)
        if have>=r.required_level: explanations.append(f'{r.skill.name} satisfied')
        else: explanations.append(f'Improve {r.skill.name} ({have}/{r.required_level})')
    skill = sum(scores)/len(scores)*100
    eligibility=100
    if student.graduation_year and opp.deadline and student.graduation_year < opp.deadline.year: eligibility=90
    career=100 if student.desired_role and any(k in student.desired_role.lower() for k in opp.title.lower().split()) else 70
    interest=80
    try:
        w={x.key:float(x.value)/100 for x in Setting.query.filter(Setting.key.in_(['skill_weight','eligibility_weight','career_weight','interest_weight'])).all()}
    except Exception:
        w={}
    total=round(skill*w.get('skill_weight',.40)+eligibility*w.get('eligibility_weight',.25)+career*w.get('career_weight',.20)+interest*w.get('interest_weight',.15),1)
    return total, explanations

def ai_recommendations(student, limit=6):
    opps=Opportunity.query.filter_by(status='Published').order_by(Opportunity.deadline.asc()).all()
    ranked=[]
    for o in opps:
        score, why=student_match(student,o); ranked.append((score,o,why))
    ranked.sort(key=lambda x:x[0], reverse=True)
    return ranked[:limit]

@app.context_processor
def inject_globals():
    unread = Notification.query.filter_by(user_id=current_user.id, read=False).count() if current_user.is_authenticated else 0
    return {'unread_notifications':unread, 'now':datetime.utcnow(), 'ROLE_HOME':ROLE_HOME, 'student_match':student_match}

ALLOWED_IMAGE_EXTENSIONS = {'png','jpg','jpeg','webp'}
ALLOWED_DOC_EXTENSIONS = {'pdf','png','jpg','jpeg','webp'}

def allowed_file(filename, extensions):
    return bool(filename and '.' in filename and filename.rsplit('.',1)[1].lower() in extensions)

def save_upload(file, prefix, extensions, max_mb=10):
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename, extensions):
        raise ValueError('Unsupported file type.')
    ext=file.filename.rsplit('.',1)[1].lower()
    try:
        file.stream.seek(0, os.SEEK_END); size=file.stream.tell(); file.stream.seek(0)
        if size > max_mb * 1024 * 1024: raise ValueError(f'File is too large. Maximum allowed size is {max_mb} MB.')
    except (AttributeError, OSError):
        pass
    safe=secure_filename(file.filename) or f'upload.{ext}'
    filename=f'{prefix}_{int(datetime.utcnow().timestamp())}_{safe}'
    file.save(os.path.join(app.config['UPLOAD_FOLDER'],filename))
    return filename

def validate_phone(value):
    import re
    return bool(not value or re.fullmatch(r'\+?[0-9 ()-]{7,20}', value))

def validate_url(value):
    if not value: return True
    from urllib.parse import urlparse
    try:
        parsed=urlparse(value if '://' in value else 'https://'+value)
        return parsed.scheme in ('http','https') and bool(parsed.netloc)
    except Exception: return False

def academic_options():
    institutions=Institution.query.order_by(Institution.name).all()
    departments=Department.query.order_by(Department.name).all()
    programs=Program.query.filter_by(active=True).order_by(Program.name).all()
    return institutions, departments, programs

# ---------- CAPTCHA / OTP helpers ----------
def make_captcha():
    a, b = random.randint(2, 9), random.randint(2, 9)
    session['captcha_answer'] = str(a + b)
    session['captcha_question'] = f'{a} + {b} = ?'

def captcha_valid(value):
    answer = session.get('captcha_answer')
    ok = bool(answer and secrets.compare_digest(str(value).strip(), answer))
    if ok:
        session.pop('captcha_answer', None)
    return ok

@app.route('/captcha/refresh')
def captcha_refresh():
    make_captcha()
    return jsonify({'question': session.get('captcha_question', 'Solve the question')})

def normalize_phone(value):
    value=(value or '').strip()
    digits=re.sub(r'[^0-9+]', '', value)
    if digits.startswith('+'):
        return '+' + re.sub(r'\D', '', digits[1:])
    return re.sub(r'\D', '', digits)

def valid_phone_e164(value):
    return bool(re.fullmatch(r'\+[1-9]\d{9,14}', normalize_phone(value)))

def send_email_otp(to_email, code):
    host=os.getenv('SMTP_HOST'); port=int(os.getenv('SMTP_PORT','587')); user=os.getenv('SMTP_USERNAME'); password=os.getenv('SMTP_PASSWORD')
    sender=os.getenv('SMTP_FROM') or user
    if not (host and user and password and sender):
        app.logger.warning('SMTP not configured. Email OTP for %s: %s', to_email, code)
        return False
    msg=EmailMessage(); msg['Subject']='AIC Portal verification code'; msg['From']=sender; msg['To']=to_email
    msg.set_content(f'Your AIC Portal verification code is {code}. It expires in {app.config["OTP_EXPIRE_MINUTES"]} minutes. Do not share this code.')
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except smtplib.SMTPAuthenticationError:
        app.logger.error("SMTP authentication failed. Check SMTP_USERNAME and use a Gmail App Password, not the normal account password.")
        app.logger.warning("DEMO MODE: Email OTP for %s: %s", to_email, code)
        return False
    except (smtplib.SMTPException, OSError) as exc:
        app.logger.error("SMTP delivery failed: %s", exc)
        app.logger.warning("DEMO MODE: Email OTP for %s: %s", to_email, code)
        return False

def send_phone_otp(to_phone, code):
    sid=os.getenv('TWILIO_ACCOUNT_SID'); token=os.getenv('TWILIO_AUTH_TOKEN'); from_phone=os.getenv('TWILIO_FROM_PHONE')
    if not (sid and token and from_phone):
        app.logger.warning('Twilio not configured. Phone OTP for %s: %s', to_phone, code)
        return False
    try:
        from twilio.rest import Client
        Client(sid, token).messages.create(body=f'AIC Portal OTP: {code}. Expires in {app.config["OTP_EXPIRE_MINUTES"]} minutes.', from_=from_phone, to=to_phone)
        return True
    except Exception:
        app.logger.exception('Failed to send phone OTP')
        return False

def issue_otp(user, channel):
    destination = user.email if channel == 'email' else normalize_phone(user.phone or (user.student.phone if user.student else ''))
    if channel == 'phone': destination=normalize_phone(destination)
    code=f'{secrets.randbelow(1000000):06d}'
    # invalidate previous active OTPs for this user/channel
    VerificationOTP.query.filter_by(user_id=user.id, channel=channel, used=False).update({'used':True})
    row=VerificationOTP(user_id=user.id, channel=channel, destination=destination,
                        code_hash=generate_password_hash(code),
                        expires_at=datetime.utcnow()+timedelta(minutes=app.config['OTP_EXPIRE_MINUTES']))
    db.session.add(row); db.session.commit()
    sent = send_email_otp(destination,code) if channel=='email' else send_phone_otp(destination,code)
    return sent

def verify_otp(user_id, channel, code):
    row=VerificationOTP.query.filter_by(user_id=user_id, channel=channel, used=False).order_by(VerificationOTP.created_at.desc()).first()
    if not row or row.expires_at < datetime.utcnow(): return False, 'OTP expired. Request a new code.'
    if row.attempts >= app.config['OTP_MAX_ATTEMPTS']: return False, 'Too many attempts. Request a new code.'
    row.attempts += 1
    if not check_password_hash(row.code_hash, str(code).strip()): db.session.commit(); return False, 'Invalid OTP.'
    row.used=True; db.session.commit(); return True, 'Verified.'

def auth_ready_user(user):
    return bool(user.email_verified and user.phone_verified)

# ---------- Public ----------
@app.route('/')
def landing():
    return render_template('landing.html', opportunities=Opportunity.query.filter_by(status='Published').limit(6).all())

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='GET':
        make_captcha()
    else:
        if not captcha_valid(request.form.get('captcha','')):
            flash('Invalid CAPTCHA. Please solve the new question.', 'danger'); make_captcha(); return render_template('auth.html',mode='login')
        u=User.query.filter_by(email=request.form.get('email','').strip().lower()).first()
        if u and u.active and check_password_hash(u.password_hash, request.form.get('password','')):
            if not auth_ready_user(u):
                session['verify_user_id']=u.id; session['verify_flow']='login'
                if not u.email_verified: issue_otp(u,'email')
                if not u.phone_verified and u.phone: issue_otp(u,'phone')
                flash('Verify your email and phone with OTP before logging in.', 'warning')
                return redirect(url_for('verify_otp_page'))
            login_user(u); audit('Login'); db.session.commit(); return redirect(url_for(ROLE_HOME.get(u.role,'student_dashboard')))
        flash('Invalid email or password.', 'danger'); make_captcha()
    return render_template('auth.html', mode='login')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='GET':
        make_captcha()
    else:
        if not captcha_valid(request.form.get('captcha','')):
            flash('Invalid CAPTCHA. Please solve the new question.', 'danger'); make_captcha(); return render_template('auth.html',mode='register')
        email=request.form.get('email','').strip().lower(); role=request.form.get('role','Student')
        phone=normalize_phone(request.form.get('phone',''))
        if User.query.filter_by(email=email).first(): flash('Email already registered.','danger'); make_captcha(); return render_template('auth.html',mode='register')
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email): flash('Enter a valid email address.','danger'); make_captcha(); return render_template('auth.html',mode='register')
        if not valid_phone_e164(phone): flash('Enter phone number in international format, e.g. +919876543210.','danger'); make_captcha(); return render_template('auth.html',mode='register')
        if role not in ROLE_HOME: role='Student'
        password=request.form.get('password','')
        if len(password)<8: flash('Password must be at least 8 characters.','danger'); make_captcha(); return render_template('auth.html',mode='register')
        # Registration does not require email/phone OTP. The contact fields are validated,
        # while verification can be handled later from the user's profile/settings.
        u=User(name=request.form.get('name','New User').strip(), email=email, phone=phone,
               password_hash=generate_password_hash(password), role=role,
               email_verified=True, phone_verified=True)
        db.session.add(u); db.session.flush()
        if role=='Student': db.session.add(StudentProfile(user_id=u.id, institution=request.form.get('institution',''), department=request.form.get('department',''), program=request.form.get('program',''), phone=phone))
        elif role=='Faculty': db.session.add(FacultyProfile(user_id=u.id, institution=request.form.get('institution',''), department=request.form.get('department','')))
        elif role=='Industry':
            c=Company(name=request.form.get('company','New Company'), industry=request.form.get('industry','Technology'), email=email, location=request.form.get('location',''), verification_status='Pending'); db.session.add(c); db.session.flush(); db.session.add(CompanyUser(user_id=u.id,company_id=c.id,title='Company Admin'))
        else:
            # Admin accounts should normally be provisioned by an existing administrator.
            flash('Administrator registration requires approval. Contact the platform administrator.', 'danger'); db.session.rollback(); make_captcha(); return render_template('auth.html',mode='register')
        db.session.commit()
        flash('Account created successfully. You can log in now.', 'success')
        return redirect(url_for('login'))
    return render_template('auth.html',mode='register')

@app.route('/verify-otp', methods=['GET','POST'])
def verify_otp_page():
    uid=session.get('verify_user_id')
    if not uid: return redirect(url_for('login'))
    u=db.session.get(User,uid)
    if not u: session.pop('verify_user_id',None); return redirect(url_for('login'))
    if request.method=='POST':
        channel=request.form.get('channel','email')
        ok,msg=verify_otp(u.id,channel,request.form.get('otp',''))
        if ok:
            if channel=='email': u.email_verified=True
            else: u.phone_verified=True
            db.session.commit()
            if u.email_verified and u.phone_verified:
                flow=session.get('verify_flow'); session.pop('verify_user_id',None); session.pop('verify_flow',None); session.pop('pending_phone',None); session.pop('verify_phone_override',None)
                if flow=='login': login_user(u); audit('Login after OTP verification'); db.session.commit(); return redirect(url_for(ROLE_HOME.get(u.role,'student_dashboard')))
                login_user(u); audit('Registration verified'); db.session.commit(); return redirect(url_for(ROLE_HOME.get(u.role,'student_dashboard')))
            flash(f'{channel.title()} verified. Verify the other channel.', 'success')
        else: flash(msg,'danger')
    return render_template('verify_otp.html', user=u, email_verified=u.email_verified, phone_verified=u.phone_verified, phone=session.get('pending_phone') or u.phone or (u.student.phone if u.student else ''))

@app.route('/resend-otp/<channel>')
def resend_otp(channel):
    uid=session.get('verify_user_id')
    if channel not in ('email','phone') or not uid: return redirect(url_for('login'))
    u=db.session.get(User,uid)
    if not u: return redirect(url_for('login'))
    issue_otp(u,channel)
    flash(f'New {channel} OTP sent.','success'); return redirect(url_for('verify_otp_page'))

@app.route('/forgot-password', methods=['GET','POST'])
def forgot():
    if request.method=='GET': make_captcha()
    else:
        if not captcha_valid(request.form.get('captcha','')):
            flash('Invalid CAPTCHA.','danger'); make_captcha(); return render_template('auth.html',mode='forgot')
        flash('If the account exists, reset instructions would be sent. Demo mode keeps this local.','success'); make_captcha()
    return render_template('auth.html',mode='forgot')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('landing'))

# ---------- Shared pages ----------
@app.route('/notifications')
@login_required
def notifications():
    items=Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    for n in items: n.read=True
    db.session.commit(); return render_template('notifications.html', items=items)

@app.route('/messages', methods=['GET','POST'])
@login_required
def messages():
    if request.method == 'POST':
        recipient_id = int(request.form.get('recipient_id', 0))
        recipient = db.session.get(User, recipient_id)
        body = request.form.get('body','').strip()
        subject = request.form.get('subject','').strip() or 'AIC Portal Message'
        if not recipient or recipient.id == current_user.id or not body:
            flash('Please select a valid recipient and enter a message.', 'danger')
        else:
            db.session.add(Message(sender_id=current_user.id, recipient_id=recipient.id, subject=subject, body=body))
            notify(recipient.id, 'New message', f'{current_user.name} sent you a message.', 'message')
            audit('Send message', recipient.email)
            db.session.commit()
            flash('Message sent successfully.', 'success')
            return redirect(url_for('messages'))
    inbox = Message.query.filter_by(recipient_id=current_user.id).order_by(Message.created_at.desc()).all()
    sent = Message.query.filter_by(sender_id=current_user.id).order_by(Message.created_at.desc()).all()
    contacts = User.query.filter(User.id != current_user.id, User.active == True).order_by(User.name).limit(100).all()
    for m in inbox:
        m.read = True
    db.session.commit()
    return render_template('messages.html', inbox=inbox, sent=sent, contacts=contacts)

@app.route('/calendar', methods=['GET','POST'])
@login_required
def calendar():
    if request.method == 'POST':
        title=request.form.get('title','').strip(); event_type=request.form.get('event_type','Meeting'); raw=request.form.get('event_date','')
        if not title or not raw:
            flash('Event title and date are required.', 'danger')
        else:
            try:
                dt=datetime.fromisoformat(raw)
                db.session.add(Event(title=title,event_type=event_type,event_date=dt,location=request.form.get('location','').strip(),description=request.form.get('description','').strip()))
                notify(current_user.id,'Calendar event created',f'{title} was added to your calendar.','calendar'); audit('Create calendar event',title); db.session.commit(); flash('Calendar event created.', 'success')
            except ValueError:
                flash('Invalid event date.', 'danger')
        return redirect(url_for('calendar'))
    events=Event.query.order_by(Event.event_date.asc()).all()
    return render_template('calendar.html', events=events)

@app.route('/support', methods=['GET','POST'])
@login_required
def support():
    if request.method=='POST':
        t=SupportTicket(user_id=current_user.id,category=request.form['category'],subject=request.form['subject'],description=request.form['description'],priority=request.form.get('priority','Normal')); db.session.add(t); notify(current_user.id,'Support ticket created',f'Ticket #{t.id} is open.','support'); audit('Create support ticket'); db.session.commit(); flash('Support ticket created.','success'); return redirect(url_for('support'))
    tickets=SupportTicket.query.filter_by(user_id=current_user.id).order_by(SupportTicket.created_at.desc()).all()
    return render_template('support.html',tickets=tickets)

# ---------- Student ----------
@app.route('/student')
@login_required
def student_root(): return redirect(url_for('student_dashboard'))

@app.route('/student/dashboard')
@role_required('Student')
def student_dashboard():
    s=current_user.student
    recs=ai_recommendations(s,5) if s else []
    gaps=[]
    if s and s.desired_role:
        role=CareerRole.query.filter_by(name=s.desired_role).first()
        if role:
            have={x.skill_id:x.level for x in s.skills}
            gaps=[(rs.skill,have.get(rs.skill_id,0),rs.required_level) for rs in role.skills if have.get(rs.skill_id,0)<rs.required_level]
    apps=Application.query.filter_by(student_id=s.id).order_by(Application.updated_at.desc()).limit(5).all() if s else []
    return render_template('student_dashboard.html',s=s,recs=recs,gaps=gaps,apps=apps)

@app.route('/student/profile',methods=['GET','POST'])
@role_required('Student')
def student_profile():
    s=current_user.student
    if request.method=='POST':
        phone=request.form.get('phone','').strip()
        gy=request.form.get('graduation_year','').strip()
        institution=request.form.get('institution','').strip()
        department=request.form.get('department','').strip()
        program=request.form.get('program','').strip()
        if not validate_phone(phone): flash('Enter a valid phone number.','danger'); return redirect(url_for('student_profile'))
        if gy and (not gy.isdigit() or not 2000 <= int(gy) <= 2100): flash('Graduation year must be between 2000 and 2100.','danger'); return redirect(url_for('student_profile'))
        if institution and not Institution.query.filter_by(name=institution).first(): flash('Please select a valid institution from the database.','danger'); return redirect(url_for('student_profile'))
        inst_obj=Institution.query.filter_by(name=institution).first() if institution else None
        dep_obj=Department.query.filter_by(name=department).first() if department else None
        prog_obj=Program.query.filter_by(name=program).first() if program else None
        if department and not dep_obj: flash('Please select a valid department from the database.','danger'); return redirect(url_for('student_profile'))
        if program and not prog_obj: flash('Please select a valid program from the database.','danger'); return redirect(url_for('student_profile'))
        if dep_obj and inst_obj and dep_obj.institution_id != inst_obj.id: flash('Selected department does not belong to the selected institution.','danger'); return redirect(url_for('student_profile'))
        if prog_obj and dep_obj and prog_obj.department_id != dep_obj.id: flash('Selected program does not belong to the selected department.','danger'); return redirect(url_for('student_profile'))
        for k in ['phone','institution','department','program','semester','location','desired_role','bio']: setattr(s,k,request.form.get(k,'').strip())
        s.graduation_year=int(gy) if gy else None
        s.visibility=request.form.get('visibility')=='on'
        resume=request.files.get('resume')
        photo=request.files.get('profile_photo')
        try:
            saved=save_upload(resume,f'resume_{current_user.id}',{'pdf','doc','docx'},10)
            if saved: s.resume=saved
            photo_name=save_upload(photo,f'avatar_{current_user.id}',ALLOWED_IMAGE_EXTENSIONS,5)
            if photo_name:
                av=UserAvatar.query.filter_by(user_id=current_user.id).first() or UserAvatar(user_id=current_user.id,filename=photo_name)
                if av.id and av.filename != photo_name:
                    old=os.path.join(app.config['UPLOAD_FOLDER'],av.filename)
                    if os.path.exists(old):
                        try: os.remove(old)
                        except OSError: pass
                av.filename=photo_name; av.updated_at=datetime.utcnow(); db.session.add(av)
        except ValueError as e:
            flash(str(e),'danger'); return redirect(url_for('student_profile'))
        audit('Update student profile'); db.session.commit(); flash('Profile updated successfully.','success'); return redirect(url_for('student_profile'))
    roles=CareerRole.query.order_by(CareerRole.name).all(); institutions,departments,programs=academic_options()
    return render_template('student_profile.html',s=s,roles=roles,institutions=institutions,departments=departments,programs=programs,certifications=Certification.query.filter_by(student_id=s.id).order_by(Certification.issue_date.desc()).all())

@app.route('/profile')
@login_required
def my_profile():
    if current_user.role=='Student': return redirect(url_for('student_profile'))
    if current_user.role=='Faculty': return redirect(url_for('faculty_profile'))
    if current_user.role=='Industry': return redirect(url_for('industry_company'))
    return redirect(url_for('admin_profile'))

@app.route('/profile/photo/delete', methods=['POST'])
@login_required
def delete_profile_photo():
    av=UserAvatar.query.filter_by(user_id=current_user.id).first()
    if av:
        path=os.path.join(app.config['UPLOAD_FOLDER'],av.filename)
        if os.path.exists(path):
            try: os.remove(path)
            except OSError: pass
        db.session.delete(av); db.session.commit(); flash('Profile photo removed.','success')
    return redirect(request.referrer or url_for('my_profile'))

@app.route('/student/certifications', methods=['GET','POST'])
@role_required('Student')
def student_certifications():
    s=current_user.student
    if request.method=='POST':
        name=request.form.get('name','').strip(); org=request.form.get('issuing_organization','').strip(); issue=request.form.get('issue_date','').strip(); expiry=request.form.get('expiry_date','').strip(); url=request.form.get('credential_url','').strip()
        if len(name)<3 or len(org)<2: flash('Certification name and issuing organization are required.','danger'); return redirect(url_for('student_certifications'))
        if not validate_url(url): flash('Enter a valid credential URL.','danger'); return redirect(url_for('student_certifications'))
        from datetime import date
        try:
            issue_date=date.fromisoformat(issue) if issue else None; expiry_date=date.fromisoformat(expiry) if expiry else None
        except ValueError: flash('Enter valid certification dates.','danger'); return redirect(url_for('student_certifications'))
        if issue_date and expiry_date and expiry_date < issue_date: flash('Expiry date cannot be before issue date.','danger'); return redirect(url_for('student_certifications'))
        cert=Certification(student_id=s.id,name=name,issuing_organization=org,certificate_id=request.form.get('certificate_id','').strip(),issue_date=issue_date,expiry_date=expiry_date,credential_url=url,description=request.form.get('description','').strip(),verification_status='Pending')
        try:
            cert.file_name=save_upload(request.files.get('certificate_file'),f'cert_{current_user.id}',ALLOWED_DOC_EXTENSIONS,10)
        except ValueError as e: flash(str(e),'danger'); return redirect(url_for('student_certifications'))
        db.session.add(cert); db.session.flush(); notify(current_user.id,'Certification added','Your certification was added and is pending verification.','certification'); audit('Add certification',cert.name); db.session.commit(); flash('Certification added. Request sent for verification.','success'); return redirect(url_for('student_certifications'))
    certs=Certification.query.filter_by(student_id=s.id).order_by(Certification.issue_date.desc()).all()
    return render_template('certifications.html',certifications=certs)

@app.route('/student/certifications/<int:cid>/delete', methods=['POST'])
@role_required('Student')
def delete_certification(cid):
    cert=db.get_or_404(Certification,cid)
    if cert.student_id!=current_user.student.id: abort(403)
    if cert.file_name:
        path=os.path.join(app.config['UPLOAD_FOLDER'],cert.file_name)
        if os.path.exists(path):
            try: os.remove(path)
            except OSError: pass
    db.session.delete(cert); audit('Delete certification',cert.name); db.session.commit(); flash('Certification deleted.','success'); return redirect(url_for('student_certifications'))

@app.route('/admin/certifications')
@role_required('Platform Admin','Super Admin')
def admin_certifications():
    return render_template('admin_certifications.html',certifications=Certification.query.order_by(Certification.created_at.desc()).all())

@app.route('/admin/certifications/<int:cid>/verify', methods=['POST'])
@role_required('Platform Admin','Super Admin')
def verify_certification(cid):
    cert=db.get_or_404(Certification,cid); status=request.form.get('status')
    if status not in {'Verified','Rejected','Pending'}: abort(400)
    cert.verification_status=status; cert.verified_by=current_user.id if status=='Verified' else None; cert.verified_at=datetime.utcnow() if status=='Verified' else None; cert.rejection_reason=request.form.get('reason','').strip() if status=='Rejected' else None
    notify(cert.student.user_id,'Certification verification',f'{cert.name}: {status}.','certification'); audit('Certification verification',cert.name,status); db.session.commit(); flash('Certification status updated.','success'); return redirect(url_for('admin_certifications'))

@app.route('/student/skills',methods=['GET','POST'])
@role_required('Student')
def student_skills():
    s=current_user.student
    if request.method=='POST':
        skill=db.session.get(Skill,int(request.form['skill_id'])); level=max(1,min(5,int(request.form['level'])))
        row=StudentSkill.query.filter_by(student_id=s.id,skill_id=skill.id).first()
        if row: row.level=level
        else: db.session.add(StudentSkill(student_id=s.id,skill_id=skill.id,level=level,verified=False))
        audit('Update skill',skill.name); db.session.commit(); flash('Skill profile updated.','success'); return redirect(url_for('student_skills'))
    return render_template('skills.html',skills=Skill.query.order_by(Skill.category,Skill.name).all(),owned=s.skills,mode='student')

@app.route('/student/assessment',methods=['GET','POST'])
@role_required('Student')
def assessment():
    s=current_user.student
    if request.method=='POST':
        skill_id=int(request.form.get('skill_id',0))
        skill=db.session.get(Skill,skill_id)
        if not skill: abort(400)
        question_ids=[int(x) for x in request.form.getlist('question_id')]
        if not question_ids: flash('Please answer the assessment questions.','danger'); return redirect(url_for('assessment',skill_id=skill_id))
        questions=AssessmentQuestion.query.filter(AssessmentQuestion.id.in_(question_ids), AssessmentQuestion.skill_id==skill_id, AssessmentQuestion.active==True).all()
        if len(questions)!=len(set(question_ids)): abort(400)
        correct=0; answer_log={}
        for q in questions:
            raw=request.form.get(f'q_{q.id}')
            try: selected=int(raw)
            except (TypeError,ValueError): selected=-1
            is_correct=(selected==q.correct_index)
            correct += 1 if is_correct else 0
            answer_log[str(q.id)]={'selected':selected,'correct':q.correct_index,'is_correct':is_correct}
        total=len(questions); percent=round(correct/total*100,2) if total else 0
        level=1 if percent<40 else 2 if percent<55 else 3 if percent<70 else 4 if percent<85 else 5
        row=StudentSkill.query.filter_by(student_id=s.id,skill_id=skill_id).first()
        if row: row.level=level; row.verified=True
        else: db.session.add(StudentSkill(student_id=s.id,skill_id=skill_id,level=level,verified=True))
        attempt=AssessmentAttempt(student_id=s.id,skill_id=skill_id,total_questions=total,correct_answers=correct,score_percent=percent,level=level,answers_json=json.dumps(answer_log))
        db.session.add(attempt)
        notify(current_user.id,'Assessment completed',f'{skill.name}: {correct}/{total} correct ({percent}%). Your verified skill level is {level}/5.','assessment')
        audit('Submit assessment',f'{skill.name}: {percent}%')
        db.session.commit()
        flash(f'Assessment complete: {correct}/{total} correct — {percent}%. Skill level updated to {level}/5.','success')
        return redirect(url_for('assessment',result=attempt.id))

    skill_id=request.args.get('skill_id',type=int)
    selected_skill=db.session.get(Skill,skill_id) if skill_id else None
    questions=[]
    if selected_skill:
        # Randomize questions and avoid repeating the last recent question set when possible.
        recent=[]
        for a in AssessmentAttempt.query.filter_by(student_id=s.id,skill_id=selected_skill.id).order_by(AssessmentAttempt.created_at.desc()).limit(3).all():
            try: recent.extend(int(qid) for qid in json.loads(a.answers_json).keys())
            except Exception: pass
        pool=AssessmentQuestion.query.filter_by(skill_id=selected_skill.id,active=True).all()
        fresh=[q for q in pool if q.id not in set(recent)]
        random.shuffle(fresh); random.shuffle(pool)
        questions=(fresh or pool)[:min(10,len(fresh or pool))]
    result=None
    rid=request.args.get('result',type=int)
    if rid:
        result=AssessmentAttempt.query.filter_by(id=rid,student_id=s.id).first()
    return render_template('assessment.html',skills=Skill.query.order_by(Skill.category,Skill.name).all(),owned=s.skills,selected_skill=selected_skill,questions=questions,result=result)

@app.route('/student/skill-gap')
@role_required('Student')
def skill_gap():
    s=current_user.student; gaps=[]; strengths=[]
    role=CareerRole.query.filter_by(name=s.desired_role).first() if s.desired_role else None
    if role:
        have={x.skill_id:x.level for x in s.skills}
        for rs in role.skills:
            val=have.get(rs.skill_id,0)
            (strengths if val>=rs.required_level else gaps).append((rs.skill,val,rs.required_level))
    return render_template('skill_gap.html',role=role,gaps=gaps,strengths=strengths)

@app.route('/student/recommendations')
@role_required('Student')
def student_recommendations(): return render_template('recommendations.html',recs=ai_recommendations(current_user.student,20))

@app.route('/student/opportunities')
@role_required('Student')
def student_opportunities():
    q=request.args.get('q','').lower(); typ=request.args.get('type','')
    query=Opportunity.query.filter_by(status='Published')
    if typ: query=query.filter_by(type=typ)
    if q: query=query.filter(Opportunity.title.ilike(f'%{q}%'))
    opps=query.order_by(Opportunity.deadline.asc()).all(); scored=[(student_match(current_user.student,o)[0],o) for o in opps]; scored.sort(reverse=True,key=lambda x:x[0])
    return render_template('opportunities.html',opps=scored)

@app.route('/student/opportunities/<int:oid>')
@role_required('Student')
def opportunity_detail(oid):
    o=db.get_or_404(Opportunity,oid); score,why=student_match(current_user.student,o); applied=Application.query.filter_by(opportunity_id=oid,student_id=current_user.student.id).first(); return render_template('opportunity_detail.html',o=o,score=score,why=why,applied=applied)

@app.route('/student/opportunities/<int:oid>/save', methods=['POST'])
@role_required('Student')
def save_opportunity(oid):
    o=db.session.get(Opportunity, oid)
    if not o or o.status != 'Published': abort(404)
    if not SavedOpportunity.query.filter_by(student_id=current_user.student.id, opportunity_id=oid).first():
        db.session.add(SavedOpportunity(student_id=current_user.student.id, opportunity_id=oid))
        audit('Save opportunity', o.title)
        db.session.commit(); flash('Opportunity saved for later.', 'success')
    else:
        flash('Opportunity is already saved.', 'warning')
    return redirect(url_for('opportunity_detail', oid=oid))

@app.route('/student/opportunities/<int:oid>/apply',methods=['POST'])
@role_required('Student')
def apply_opportunity(oid):
    o=db.get_or_404(Opportunity,oid); s=current_user.student
    if o.status!='Published': abort(400)
    if Application.query.filter_by(opportunity_id=oid,student_id=s.id).first(): flash('You already applied.','warning'); return redirect(url_for('opportunity_detail',oid=oid))
    score,_=student_match(s,o); a=Application(opportunity_id=oid,student_id=s.id,match_score=score,status='Submitted'); db.session.add(a); db.session.flush(); db.session.add(ApplicationHistory(application_id=a.id,status='Submitted',actor_id=current_user.id)); notify(current_user.id,'Application submitted',f'Application for {o.title} was submitted.','application')
    for cu in o.company.users: notify(cu.user_id,'New application',f'{s.user.name} applied for {o.title}.','recruitment')
    audit('Apply',f'Opportunity #{oid}'); db.session.commit(); flash('Application submitted successfully.','success'); return redirect(url_for('student_applications'))

@app.route('/student/applications')
@role_required('Student')
def student_applications(): return render_template('applications.html',apps=Application.query.filter_by(student_id=current_user.student.id).order_by(Application.updated_at.desc()).all(),student_view=True)

@app.route('/student/portfolio',methods=['GET','POST'])
@role_required('Student')
def portfolio():
    if request.method=='POST': db.session.add(PortfolioProject(student_id=current_user.student.id,title=request.form['title'],description=request.form['description'],link=request.form.get('link',''))); db.session.commit(); flash('Project added to portfolio.','success'); return redirect(url_for('portfolio'))
    projects=PortfolioProject.query.filter_by(student_id=current_user.student.id).all(); return render_template('portfolio.html',projects=projects)

@app.route('/student/courses',methods=['GET','POST'])
@role_required('Student')
def student_courses():
    s=current_user.student
    if request.method=='POST':
        action=request.form.get('action','enroll'); cid=int(request.form.get('course_id',0))
        c=db.session.get(Course,cid)
        if not c: abort(404)
        e=LearningEnrollment.query.filter_by(student_id=s.id,resource_type='course',resource_id=cid).first()
        if action=='enroll':
            if e: flash('You already enrolled in this course.','warning')
            else:
                e=LearningEnrollment(student_id=s.id,resource_type='course',resource_id=cid,status='Pending Verification',progress=0,attendance_percent=0)
                db.session.add(e); db.session.flush(); notify(current_user.id,'Course enrollment submitted',f'Your enrollment for {c.title} is pending verification.','learning'); notify_admins('Course enrollment requires verification',f'{current_user.name} requested enrollment in {c.title}.'); audit('Course enrollment',c.title); flash('Enrollment submitted for verification.','success')
        elif action in ('progress','complete'):
            if not e: flash('Enroll first.','warning')
            elif e.status not in ('Approved','Completed'): flash('Your enrollment must be approved before learning progress can be recorded.','warning')
            else:
                val=max(0,min(100,int(request.form.get('progress',e.progress))))
                e.progress=val; e.attendance_percent=max(e.attendance_percent, min(100,int(request.form.get('attendance',e.attendance_percent))))
                if action=='complete' or (e.progress>=100 and e.attendance_percent>=75): e.progress=100; e.completed=True; e.status='Completed'; e.completion_date=datetime.utcnow(); notify(current_user.id,'Course completed',f'You completed {c.title}.','learning'); audit('Complete course',c.title); flash('Course marked completed.','success')
                else: flash('Learning progress updated.','success')
        db.session.commit(); return redirect(url_for('student_courses'))
    courses=Course.query.order_by(Course.title).all()
    enrollments={e.resource_id:e for e in LearningEnrollment.query.filter_by(student_id=s.id,resource_type='course').all()}
    skill_levels={x.skill_id:x.level for x in s.skills}
    recommended_course_ids={c.id for c in courses if c.skill_id not in skill_levels or skill_levels.get(c.skill_id,0)<3}
    return render_template('courses.html',courses=courses,enrollments=enrollments,progress={k:v for k,v in enrollments.items()},recommended_course_ids=recommended_course_ids)

@app.route('/student/fdps', methods=['GET','POST'])
@role_required('Student')
def student_fdps():
    # FDP is intentionally not part of the Student portal.
    abort(403)

@app.route('/learning/enrollment/<int:eid>/update',methods=['POST'])
@role_required('Student')
def update_learning_enrollment(eid):
    e=db.get_or_404(LearningEnrollment,eid)
    if e.student_id!=current_user.student.id: abort(403)
    if e.status not in ('Approved','Completed'): flash('Enrollment is not approved yet.','warning'); return redirect(request.referrer or url_for('student_courses'))
    e.attendance_percent=max(0,min(100,int(request.form.get('attendance',e.attendance_percent))))
    e.progress=max(0,min(100,int(request.form.get('progress',e.progress))))
    if e.progress>=100 and e.attendance_percent>=75:
        e.completed=True; e.status='Completed'; e.completion_date=datetime.utcnow(); notify(current_user.id,'Learning completed','Your learning activity has been marked completed.','learning'); audit('Complete learning activity',f'{e.resource_type} #{e.resource_id}')
    db.session.commit(); flash('Learning record updated.','success'); return redirect(request.referrer or url_for('student_courses'))

@app.route('/student/mentorship', methods=['GET','POST'])
@role_required('Student')
def student_mentorship():
    if request.method == 'POST':
        mid = int(request.form.get('mentorship_id', 0))
        program = db.session.get(Mentorship, mid)
        if not program:
            flash('Mentorship program not found.', 'danger')
        elif MentorshipRequest.query.filter_by(mentorship_id=mid, student_id=current_user.student.id).first():
            flash('You already requested this mentorship track.', 'warning')
        else:
            db.session.add(MentorshipRequest(mentorship_id=mid, student_id=current_user.student.id, note=request.form.get('note','').strip()))
            notify(current_user.id, 'Mentorship request submitted', f'Your request for {program.title} is pending review.', 'mentorship')
            audit('Request mentorship', program.title)
            db.session.commit(); flash('Mentorship request submitted.', 'success')
        return redirect(url_for('student_mentorship'))
    programs=Mentorship.query.order_by(Mentorship.status, Mentorship.title).all()
    requests=MentorshipRequest.query.filter_by(student_id=current_user.student.id).order_by(MentorshipRequest.created_at.desc()).all()
    return render_template('mentorship.html', programs=programs, requests=requests)

@app.route('/student/saved-opportunities', methods=['GET','POST'])
@role_required('Student')
def saved_opportunities():
    if request.method == 'POST':
        oid=int(request.form.get('opportunity_id',0)); o=db.session.get(Opportunity,oid)
        if o and not SavedOpportunity.query.filter_by(student_id=current_user.student.id, opportunity_id=oid).first():
            db.session.add(SavedOpportunity(student_id=current_user.student.id, opportunity_id=oid)); db.session.commit(); flash('Opportunity saved.', 'success')
        return redirect(url_for('saved_opportunities'))
    rows=SavedOpportunity.query.filter_by(student_id=current_user.student.id).order_by(SavedOpportunity.created_at.desc()).all()
    return render_template('saved_opportunities.html', rows=rows)

@app.route('/student/saved-opportunities/<int:oid>/remove', methods=['POST'])
@role_required('Student')
def remove_saved_opportunity(oid):
    row=SavedOpportunity.query.filter_by(student_id=current_user.student.id, opportunity_id=oid).first()
    if row: db.session.delete(row); db.session.commit(); flash('Opportunity removed from saved list.', 'success')
    return redirect(url_for('saved_opportunities'))

# ---------- Faculty ----------
@app.route('/faculty')
@login_required
def faculty_root(): return redirect(url_for('faculty_dashboard'))
@app.route('/faculty/dashboard')
@role_required('Faculty')
def faculty_dashboard():
    students=StudentProfile.query.limit(8).all(); return render_template('faculty_dashboard.html',students=students,guidance=Guidance.query.filter_by(faculty_id=current_user.faculty.id).count())
@app.route('/faculty/profile',methods=['GET','POST'])
@role_required('Faculty')
def faculty_profile():
    f=current_user.faculty
    if request.method=='POST':
        institution=request.form.get('institution','').strip(); department=request.form.get('department','').strip(); experience=request.form.get('experience','').strip()
        inst_obj=Institution.query.filter_by(name=institution).first() if institution else None
        dep_obj=Department.query.filter_by(name=department).first() if department else None
        if institution and not inst_obj: flash('Please select a valid institution.','danger'); return redirect(url_for('faculty_profile'))
        if department and not dep_obj: flash('Please select a valid department.','danger'); return redirect(url_for('faculty_profile'))
        if dep_obj and inst_obj and dep_obj.institution_id != inst_obj.id: flash('Selected department does not belong to the selected institution.','danger'); return redirect(url_for('faculty_profile'))
        if experience and len(experience)>80: flash('Experience is too long.','danger'); return redirect(url_for('faculty_profile'))
        for k in ['institution','department','designation','qualifications','experience','expertise','research']: setattr(f,k,request.form.get(k,'').strip())
        photo=request.files.get('profile_photo')
        try:
            photo_name=save_upload(photo,f'avatar_{current_user.id}',ALLOWED_IMAGE_EXTENSIONS,5)
            if photo_name:
                av=UserAvatar.query.filter_by(user_id=current_user.id).first() or UserAvatar(user_id=current_user.id,filename=photo_name)
                av.filename=photo_name; av.updated_at=datetime.utcnow(); db.session.add(av)
        except ValueError as e: flash(str(e),'danger'); return redirect(url_for('faculty_profile'))
        audit('Update faculty profile'); db.session.commit(); flash('Faculty profile updated successfully.','success'); return redirect(url_for('faculty_profile'))
    institutions,departments,programs=academic_options()
    return render_template('faculty_profile.html',f=f,institutions=institutions,departments=departments,programs=programs)

@app.route('/faculty/students')
@role_required('Faculty')
def faculty_students(): return render_template('faculty_students.html',students=StudentProfile.query.all())
@app.route('/faculty/students/<int:sid>',methods=['GET','POST'])
@role_required('Faculty')
def faculty_student_detail(sid):
    s=db.get_or_404(StudentProfile,sid)
    if request.method=='POST': db.session.add(Guidance(faculty_id=current_user.faculty.id,student_id=s.id,note=request.form['note'],action=request.form.get('action','Review progress'))); notify(s.user_id,'Faculty guidance received',f'{current_user.name} added guidance to your profile.','mentorship'); db.session.commit(); flash('Guidance saved and student notified.','success'); return redirect(url_for('faculty_student_detail',sid=sid))
    return render_template('faculty_student_detail.html',s=s,guidance=Guidance.query.filter_by(student_id=s.id).order_by(Guidance.created_at.desc()).all())
@app.route('/faculty/learning', methods=['GET','POST'])
@role_required('Faculty')
def faculty_learning():
    items=Opportunity.query.filter(Opportunity.type.in_(['FDP','Training']),Opportunity.status=='Published').order_by(Opportunity.deadline.asc()).all()
    return render_template('learning_programs.html',title='Faculty Learning',heading='FDPs & Industrial Training',items=items,enrollments={},kind='faculty')

@app.route('/faculty/opportunities')
@role_required('Faculty')
def faculty_opportunities(): return render_template('generic.html',title='Faculty Opportunities',subtitle='Industrial training, FDPs, courses and certifications',module='Faculty Opportunities',items=Opportunity.query.filter(Opportunity.type.in_(['FDP','Training'])).all())
@app.route('/faculty/collaboration')
@role_required('Faculty')
def faculty_collaboration(): return render_template('generic.html',title='Industry Connect & Research',subtitle='Industry collaboration, projects and research',module='Collaboration',items=Company.query.filter_by(verification_status='Approved').all())

# ---------- Industry ----------
def my_company(): return current_user.company_user.company
@app.route('/industry')
@login_required
def industry_root(): return redirect(url_for('industry_dashboard'))
@app.route('/industry/dashboard')
@role_required('Industry')
def industry_dashboard():
    c=my_company(); apps=Application.query.join(Opportunity).filter(Opportunity.company_id==c.id).all(); return render_template('industry_dashboard.html',c=c,apps=apps)
@app.route('/industry/company',methods=['GET','POST'])
@role_required('Industry')
def industry_company():
    c=my_company()
    if request.method=='POST':
        email=request.form.get('email','').strip().lower(); website=request.form.get('website','').strip()
        if email and ('@' not in email or len(email)>180): flash('Enter a valid official email.','danger'); return redirect(url_for('industry_company'))
        if not validate_url(website): flash('Enter a valid website URL.','danger'); return redirect(url_for('industry_company'))
        for k in ['name','industry','website','email','location','size','description']: setattr(c,k,request.form.get(k,'').strip())
        photo=request.files.get('profile_photo')
        try:
            photo_name=save_upload(photo,f'company_avatar_{c.id}',ALLOWED_IMAGE_EXTENSIONS,5)
            if photo_name:
                av=UserAvatar.query.filter_by(user_id=current_user.id).first() or UserAvatar(user_id=current_user.id,filename=photo_name)
                av.filename=photo_name; av.updated_at=datetime.utcnow(); db.session.add(av)
        except ValueError as e: flash(str(e),'danger'); return redirect(url_for('industry_company'))
        c.verification_status='Pending'; audit('Update company profile',c.name); db.session.commit(); flash('Company profile saved and sent for verification.','success'); return redirect(url_for('industry_company'))
    return render_template('company_profile.html',c=c)
@app.route('/industry/skills',methods=['GET','POST'])
@role_required('Industry')
def industry_skills():
    c=my_company()
    if request.method=='POST': db.session.add(CompanySkill(company_id=c.id,skill_id=int(request.form['skill_id']),priority=request.form.get('priority','High'),level=int(request.form.get('level',3)))); db.session.commit(); flash('Industry skill requirement added.','success'); return redirect(url_for('industry_skills'))
    return render_template('industry_skills.html',c=c,skills=Skill.query.all())
@app.route('/industry/opportunities',methods=['GET','POST'])
@role_required('Industry')
def industry_opportunities():
    c=my_company()
    if request.method=='POST':
        deadline=datetime.fromisoformat(request.form['deadline']) if request.form.get('deadline') else datetime.utcnow()+timedelta(days=30)
        o=Opportunity(company_id=c.id,type=request.form['type'],title=request.form['title'],description=request.form['description'],eligibility=request.form.get('eligibility',''),openings=int(request.form.get('openings',1)),location=request.form.get('location',''),mode=request.form.get('mode','Hybrid'),duration=request.form.get('duration',''),compensation=request.form.get('compensation',''),deadline=deadline,status='Submitted'); db.session.add(o); db.session.commit(); notify_admins('New opportunity submitted',f'{c.name} submitted {o.title} for approval.'); flash('Opportunity submitted for admin approval.','success'); return redirect(url_for('industry_opportunities'))
    return render_template('industry_opportunities.html',opps=Opportunity.query.filter_by(company_id=c.id).order_by(Opportunity.created_at.desc()).all(),my_company=c)

def notify_admins(title,body):
    for u in User.query.filter(User.role.in_(['Institution Admin','Platform Admin','Super Admin'])).all(): notify(u.id,title,body,'approval')

@app.route('/industry/candidates')
@role_required('Industry')
def industry_candidates():
    c=my_company(); students=StudentProfile.query.filter_by(visibility=True).all(); ranked=[]
    for s in students:
        best=0; bestopp=None
        for o in c.opportunities:
            sc,_=student_match(s,o); best=max(best,sc); bestopp=o
        ranked.append((best,s,bestopp))
    ranked.sort(reverse=True,key=lambda x:x[0]); return render_template('candidates.html',ranked=ranked)
@app.route('/industry/applications')
@role_required('Industry')
def industry_applications():
    c=my_company(); apps=Application.query.join(Opportunity).filter(Opportunity.company_id==c.id).order_by(Application.updated_at.desc()).all(); return render_template('applications.html',apps=apps,student_view=False)
@app.route('/industry/applications/<int:aid>/status',methods=['POST'])
@role_required('Industry')
def update_application(aid):
    a=db.get_or_404(Application,aid); c=my_company()
    if a.opportunity.company_id!=c.id: abort(403)
    new=request.form['status']; allowed=['Submitted','Under Review','Shortlisted','Assessment','Interview','Selected','Rejected','Withdrawn','Closed']
    if new not in allowed: abort(400)
    a.status=new; a.updated_at=datetime.utcnow(); db.session.add(ApplicationHistory(application_id=a.id,status=new,note=request.form.get('note',''),actor_id=current_user.id)); notify(a.student.user_id,'Application updated',f'{a.opportunity.title}: {new}.','application'); audit('Application status change',f'Application #{aid}',new); db.session.commit(); flash('Application stage updated and student notified.','success'); return redirect(url_for('industry_applications'))

# ---------- Admin ----------
@app.route('/admin')
@login_required
def admin_root(): return redirect(url_for('admin_dashboard'))
@app.route('/admin/dashboard')
@role_required('Institution Admin','Platform Admin','Super Admin')
def admin_dashboard():
    return render_template('admin_dashboard.html',stats={'users':User.query.count(),'companies':Company.query.filter_by(verification_status='Approved').count(),'opportunities':Opportunity.query.count(),'applications':Application.query.count(),'pending':Company.query.filter_by(verification_status='Pending').count()})
@app.route('/admin/users')
@role_required('Platform Admin','Super Admin','Institution Admin')
def admin_users(): return render_template('admin_users.html',users=User.query.order_by(User.created_at.desc()).all())
@app.route('/admin/companies')
@role_required('Platform Admin','Super Admin','Institution Admin')
def admin_companies(): return render_template('admin_companies.html',companies=Company.query.order_by(Company.id.desc()).all())
@app.route('/admin/companies/<int:cid>/verify',methods=['POST'])
@role_required('Platform Admin','Super Admin')
def verify_company(cid):
    c=db.get_or_404(Company,cid); c.verification_status=request.form['status']; audit('Company verification',c.name,c.verification_status)
    for cu in c.users: notify(cu.user_id,'Company verification update',f'Company status: {c.verification_status}.','verification')
    db.session.commit(); flash('Company verification updated.','success'); return redirect(url_for('admin_companies'))
@app.route('/admin/opportunities')
@role_required('Platform Admin','Super Admin','Institution Admin')
def admin_opportunities(): return render_template('admin_opportunities.html',opps=Opportunity.query.order_by(Opportunity.created_at.desc()).all())
@app.route('/admin/opportunities/<int:oid>/approve',methods=['POST'])
@role_required('Platform Admin','Super Admin')
def approve_opportunity(oid):
    o=db.get_or_404(Opportunity,oid); o.status=request.form['status']; audit('Opportunity moderation',o.title,o.status)
    for cu in o.company.users: notify(cu.user_id,'Opportunity moderation',f'{o.title} is now {o.status}.','approval')
    db.session.commit(); flash('Opportunity status updated.','success'); return redirect(url_for('admin_opportunities'))
@app.route('/admin/skills',methods=['GET','POST'])
@role_required('Platform Admin','Super Admin')
def admin_skills():
    if request.method=='POST': db.session.add(Skill(name=request.form['name'],category=request.form.get('category','General'),level=request.form.get('level','Intermediate'))); db.session.commit(); flash('Skill added.','success'); return redirect(url_for('admin_skills'))
    return render_template('admin_skills.html',skills=Skill.query.order_by(Skill.category,Skill.name).all())
@app.route('/admin/profile', methods=['GET','POST'])
@role_required('Institution Admin','Platform Admin','Super Admin')
def admin_profile():
    if request.method=='POST':
        name=request.form.get('name','').strip()
        if len(name)<2: flash('Name must contain at least 2 characters.','danger'); return redirect(url_for('admin_profile'))
        current_user.name=name
        try:
            photo_name=save_upload(request.files.get('profile_photo'),f'avatar_{current_user.id}',ALLOWED_IMAGE_EXTENSIONS,5)
            if photo_name:
                av=UserAvatar.query.filter_by(user_id=current_user.id).first() or UserAvatar(user_id=current_user.id,filename=photo_name)
                av.filename=photo_name; av.updated_at=datetime.utcnow(); db.session.add(av)
        except ValueError as e: flash(str(e),'danger'); return redirect(url_for('admin_profile'))
        audit('Update admin profile'); db.session.commit(); flash('Profile updated successfully.','success'); return redirect(url_for('admin_profile'))
    return render_template('admin_profile.html')

@app.route('/admin/settings',methods=['GET','POST'])
@role_required('Super Admin','Platform Admin')
def admin_settings():
    if request.method=='POST':
        for k in ['skill_weight','eligibility_weight','career_weight','interest_weight']:
            row=Setting.query.filter_by(key=k).first() or Setting(key=k); row.value=request.form.get(k,''); db.session.add(row)
        db.session.commit(); flash('Matching weights saved.','success')
    settings={s.key:s.value for s in Setting.query.all()}; return render_template('admin_settings.html',settings=settings)
@app.route('/admin/audit')
@role_required('Platform Admin','Super Admin')
def admin_audit(): return render_template('admin_audit.html',logs=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all())
@app.route('/admin/analytics')
@role_required('Institution Admin','Platform Admin','Super Admin')
def admin_analytics():
    return render_template('analytics.html',labels=['Users','Companies','Opportunities','Applications','Courses'],values=[User.query.count(),Company.query.count(),Opportunity.query.count(),Application.query.count(),Course.query.count()])

# ---------- Database-backed module center ----------
GENERIC = {
 'privacy':('Privacy & Consent','Control profile visibility and data access.'), 'career-roadmap':('Career Roadmap','Target role → skills → gaps → learning → opportunities.'),
 'certifications':('Certifications','Track credentials and evidence.'), 'learning-progress':('Learning Progress','Monitor course progress and completed learning.'),
 'saved-opportunities':('Saved Opportunities','Your saved marketplace items.'), 'workshops-events':('Workshops & Events','Events, workshops and guest sessions.'),
 'innovation-challenges':('Innovation Challenges','Challenges, hackathons and industry problem statements.'), 'career-readiness':('Career Readiness','Readiness score, strengths and next actions.'), 'skill-progress':('Skill Progress','Track verified and developing skills.'),
 'settings':('Settings','Account and platform preferences.'), 'industry-connect':('Industry Connect','Discover verified companies and collaboration options.'), 'research':('Research Collaboration','Research and consultancy opportunities.'),
 'fdps':('FDPs','Faculty development programs and industrial training.'), 'analytics':('Analytics','Role-aware performance and engagement analytics.'), 'team':('Organization & Team','Company team and access management.'),
 'reports':('Reports','Operational and outcome reports.'), 'approval-center':('Approval Center','Review pending governance actions.'), 'moderation':('Content Moderation','Review and moderate submitted content.'), 'system-health':('System Health','Platform health and operational checks.'),
 'matching-rules':('Matching Rules','Configure transparent matching weights.'), 'skill-role-mapping':('Skill–Role Mapping','Map skills to career roles.'), 'course-mapping':('Course Mapping','Map learning resources to skills.'), 'recommendation-analytics':('Recommendation Analytics','Measure recommendation quality.'),
 'verification-center':('Verification Center','Company and content verification.'), 'security-access':('Security & Access','Access and security controls.'), 'consent-management':('Consent Management','Review consent records.'), 'policies':('Policies','Platform policies and governance.'), 'announcements':('Announcements','Publish platform announcements.'), 'integrations':('Integrations','Integration-ready provider interfaces.'), 'system-config':('System Configuration','Platform configuration.'),
 'organization-team':('Organization & Team','Manage company users.'), 'training-programs':('Training Programs','Industry training programs.'), 'certification-programs':('Certification Programs','Industry certification programs.'), 'skill-assessments':('Skill Assessments','Industry assessment programs.'), 'mentorship-industry':('Mentorship','Mentorship programs and requests.'), 'workshops-guest-lectures':('Workshops & Guest Lectures','Industry-academia events.'), 'recruitment-analytics':('Recruitment Analytics','Recruitment funnel and selection analytics.'), 'skill-demand':('Skill Demand Insights','Industry demand by skill.'), 'team-access':('Team & Access','Team roles and access.'),
 'assigned-students':('Assigned Students','Authorized students under guidance.'), 'student-records':('Student Records','Authorized student records.'), 'guidance':('Recommendations & Guidance','Guidance actions and recommendations.'), 'student-progress':('Student Progress','Monitor student progress.'), 'courses-certifications':('Courses & Certifications','Professional development resources.'), 'mentorship-faculty':('Mentorship','Mentorship and student support.'), 'faculty-analytics':('Analytics','Faculty participation and student progress.'),
 'institutions':('Institutions','Institution registry.'), 'departments-programs':('Departments & Programs','Institution academic structure.'), 'institutional-access':('Institutional Access','Scoped access controls.'), 'industry-categories':('Industry Categories','Manage industry categories.'), 'career-roles':('Career Roles','Manage target career roles.'), 'skill-frameworks':('Skill Frameworks','Manage skill frameworks.'), 'assessments':('Assessment Management','Question bank and scoring rules.'), 'courses-programs':('Courses & Programs','Learning catalog management.'), 'fdfs':('FDPs','FDP management.'), 'mentorship-programs':('Mentorship Programs','Mentorship management.'), 'industry-projects':('Industry Projects','Project collaboration.'), 'data-management':('Data Management','Data operations.'), 'platform-analytics':('Platform Analytics','Platform-wide analytics.'), 'student-analytics':('Student Analytics','Student outcome analytics.'), 'faculty-analytics-admin':('Faculty Analytics','Faculty analytics.'), 'industry-analytics':('Industry Analytics','Industry analytics.'), 'roles-permissions':('Roles & Permissions','Role-based authorization.'), 'activity-logs':('Activity Logs','Recent user actions.'), 'access-logs':('Data Access Logs','Protected data access logs.'), 'support-center':('Support Center','Manage support tickets.'), 'profile-settings':('Profile & Settings','Administrator profile and settings.'),
 'apprenticeships':('Apprenticeships','Apprenticeship opportunities.'), 'live-projects':('Live Projects','Industry live projects.'), 'jobs':('Jobs & Placements','Job and placement opportunities.'), 'internships':('Internships','Internship marketplace.'),
}

MODULE_ROLE_RULES = {
 # Institution governance
 'institutions': {'Institution Admin','Platform Admin','Super Admin'},
 'departments-programs': {'Institution Admin','Platform Admin','Super Admin'},
 'institutional-access': {'Institution Admin','Platform Admin','Super Admin'},
 # Platform governance / security
 'roles-permissions': {'Platform Admin','Super Admin'},
 'system-health': {'Platform Admin','Super Admin'},
 'security-access': {'Platform Admin','Super Admin'},
 'matching-rules': {'Platform Admin','Super Admin'},
 'skill-role-mapping': {'Platform Admin','Super Admin'},
 'course-mapping': {'Platform Admin','Super Admin'},
 'verification-center': {'Platform Admin','Super Admin'},
 'approval-center': {'Platform Admin','Super Admin'},
 'moderation': {'Platform Admin','Super Admin'},
 'data-management': {'Platform Admin','Super Admin'},
 'access-logs': {'Platform Admin','Super Admin'},
 'activity-logs': {'Platform Admin','Super Admin'},
 'audit-logs': {'Platform Admin','Super Admin'},
 'profile-settings': {'Institution Admin','Platform Admin','Super Admin'},
 # Operational administration
 'industry-categories': {'Platform Admin','Super Admin'},
 'career-roles': {'Platform Admin','Super Admin'},
 'skill-frameworks': {'Platform Admin','Super Admin'},
 'assessments': {'Platform Admin','Super Admin'},
 'courses-programs': {'Platform Admin','Super Admin'},
 'fdfs': {'Platform Admin','Super Admin'},
 'mentorship-programs': {'Platform Admin','Super Admin'},
 'support-center': {'Institution Admin','Platform Admin','Super Admin'},
 # Faculty authority
 'assigned-students': {'Faculty','Institution Admin','Platform Admin','Super Admin'},
 'student-records': {'Faculty','Institution Admin','Platform Admin','Super Admin'},
 'guidance': {'Faculty','Institution Admin','Platform Admin','Super Admin'},
 'student-progress': {'Faculty','Institution Admin','Platform Admin','Super Admin'},
 # Industry authority
 'organization-team': {'Industry','Platform Admin','Super Admin'},
 'team-access': {'Industry','Platform Admin','Super Admin'},
 'training-programs': {'Industry','Platform Admin','Super Admin'},
 'certification-programs': {'Industry','Platform Admin','Super Admin'},
 'skill-assessments': {'Industry','Platform Admin','Super Admin'},
 'industry-connect': {'Faculty','Industry','Institution Admin','Platform Admin','Super Admin'},
 'research': {'Faculty','Industry','Institution Admin','Platform Admin','Super Admin'},
 'industry-projects': {'Faculty','Industry','Institution Admin','Platform Admin','Super Admin'},
}

def module_scope(slug):
    # Every module reads shared entities where meaningful; otherwise it reads/writes ModuleRecord rows.
    if slug in ('workshops-events','workshops-guest-lectures'):
        return Event.query.order_by(Event.event_date.asc()).all(), 'event'
    if slug in ('institutions',): return Institution.query.order_by(Institution.name).all(), 'institution'
    if slug in ('departments-programs',): return Department.query.order_by(Department.name).all(), 'department'
    if slug in ('career-roles',): return CareerRole.query.order_by(CareerRole.name).all(), 'career_role'
    if slug in ('skill-frameworks','skill-role-mapping'): return Skill.query.order_by(Skill.category,Skill.name).all(), 'skill'
    if slug in ('courses-programs','courses-certifications','certifications','fdps','training-programs','certification-programs'):
        return Course.query.order_by(Course.title).all(), 'course'
    if slug in ('internships','jobs','apprenticeships','live-projects'):
        typ={'internships':'Internship','jobs':'Job','apprenticeships':'Apprenticeship','live-projects':'Live Project'}[slug]
        return Opportunity.query.filter_by(type=typ).order_by(Opportunity.deadline.asc()).all(), 'opportunity'
    if slug in ('industry-connect',): return Company.query.filter_by(verification_status='Approved').order_by(Company.name).all(), 'company'
    if slug in ('assigned-students','student-records','student-progress','student-analytics'):
        return StudentProfile.query.order_by(StudentProfile.id).all(), 'student'
    if slug in ('analytics','platform-analytics','faculty-analytics','faculty-analytics-admin','industry-analytics','recruitment-analytics','recommendation-analytics','skill-demand','reports'):
        return [], 'analytics'
    if slug in ('guidance',): return Guidance.query.order_by(Guidance.created_at.desc()).all(), 'guidance'
    if slug in ('support-center',):
        if current_user.role in {'Platform Admin','Super Admin','Institution Admin'}:
            return SupportTicket.query.order_by(SupportTicket.created_at.desc()).all(), 'support'
        return SupportTicket.query.filter_by(user_id=current_user.id).order_by(SupportTicket.created_at.desc()).all(), 'support'
    if slug in ('mentorship-programs','mentorship-industry','mentorship-faculty'):
        return Mentorship.query.order_by(Mentorship.title).all(), 'mentorship'
    return ModuleRecord.query.filter_by(module=slug).order_by(ModuleRecord.created_at.desc()).all(), 'record'

@app.route('/portal/<slug>', methods=['GET','POST'])
@login_required
def generic_portal(slug):
    if slug not in GENERIC: abort(404)
    if slug in MODULE_ROLE_RULES and current_user.role not in MODULE_ROLE_RULES[slug]: abort(403)
    title, subtitle = GENERIC[slug]
    # special student saved-opportunities page
    if slug == 'saved-opportunities': return redirect(url_for('saved_opportunities'))
    # Real learning catalogs: enrollment and verification workflows
    if slug == 'fdps' and current_user.role == 'Student': return redirect(url_for('student_fdps'))
    if slug in ('courses-certifications','courses-programs') and current_user.role == 'Student': return redirect(url_for('student_courses'))
    # Real academic registry modules
    if slug in ('institutions','departments-programs'):
        if request.method=='POST':
            action=request.form.get('action','create')
            if action=='institution':
                name=request.form.get('name','').strip(); city=request.form.get('city','').strip()
                if len(name)<3: flash('Institution name must contain at least 3 characters.','danger')
                elif Institution.query.filter_by(name=name).first(): flash('Institution already exists.','danger')
                else: db.session.add(Institution(name=name,city=city)); audit('Create institution',name); db.session.commit(); flash('Institution added.','success')
            elif action=='department':
                name=request.form.get('name','').strip(); iid=request.form.get('institution_id','')
                inst=db.session.get(Institution,int(iid)) if iid.isdigit() else None
                if not inst or len(name)<2: flash('Select a valid institution and enter a valid department name.','danger')
                elif Department.query.filter_by(name=name,institution_id=inst.id).first(): flash('Department already exists for this institution.','danger')
                else: db.session.add(Department(name=name,institution_id=inst.id)); audit('Create department',name); db.session.commit(); flash('Department added.','success')
            elif action=='program':
                name=request.form.get('name','').strip(); did=request.form.get('department_id',''); dep=db.session.get(Department,int(did)) if did.isdigit() else None
                if not dep or len(name)<2: flash('Select a valid department and enter a valid program name.','danger')
                elif Program.query.filter_by(name=name,department_id=dep.id).first(): flash('Program already exists for this department.','danger')
                else: db.session.add(Program(name=name,department_id=dep.id,level=request.form.get('level','Undergraduate'),duration=request.form.get('duration',''))); audit('Create program',name); db.session.commit(); flash('Program added.','success')
            return redirect(url_for('generic_portal',slug=slug))
        institutions,departments,programs=academic_options()
        return render_template('academic_registry.html',title=title,subtitle=subtitle,institutions=institutions,departments=departments,programs=programs,slug=slug)
    if slug == 'certifications' and current_user.role=='Student':
        return redirect(url_for('student_certifications'))
    if slug == 'verification-center' and current_user.role in {'Platform Admin','Super Admin'}:
        return redirect(url_for('admin_certifications'))
    # special shared calendar-like modules
    if request.method == 'POST' and slug in MODULE_ROLE_RULES and current_user.role not in MODULE_ROLE_RULES[slug]:
        abort(403)
    if request.method == 'POST':
        action=request.form.get('action','create')
        if action == 'delete':
            rid=int(request.form.get('record_id',0)); rec=db.session.get(ModuleRecord,rid)
            if rec and rec.module==slug and (rec.owner_id==current_user.id or current_user.role in {'Platform Admin','Super Admin'}):
                db.session.delete(rec); audit('Delete module record', title, rec.title); db.session.commit(); flash('Record deleted.', 'success')
            return redirect(url_for('generic_portal',slug=slug))
        if action == 'status':
            rid=int(request.form.get('record_id',0)); rec=db.session.get(ModuleRecord,rid)
            if rec and rec.module==slug:
                rec.status=request.form.get('status','Active'); rec.updated_at=datetime.utcnow(); audit('Update module status', title, rec.title); db.session.commit(); flash('Status updated.', 'success')
            return redirect(url_for('generic_portal',slug=slug))
        rec=ModuleRecord(module=slug,title=request.form.get('title','').strip(),description=request.form.get('description','').strip(),category=request.form.get('category','').strip(),status=request.form.get('status','Active'),location=request.form.get('location','').strip(),owner_id=current_user.id)
        d=request.form.get('due_date','').strip()
        if d:
            try: rec.due_date=datetime.fromisoformat(d)
            except ValueError: pass
        if not rec.title:
            flash('Title is required.', 'danger')
        else:
            db.session.add(rec); audit('Create module record', title, rec.title); db.session.commit(); flash(f'{title} record created.', 'success')
        return redirect(url_for('generic_portal',slug=slug))
    items, kind = module_scope(slug)
    stats = {}
    if kind == 'analytics':
        stats={'Users':User.query.count(),'Students':StudentProfile.query.count(),'Faculty':FacultyProfile.query.count(),'Companies':Company.query.filter_by(verification_status='Approved').count(),'Opportunities':Opportunity.query.count(),'Applications':Application.query.count(),'Selected':Application.query.filter_by(status='Selected').count(),'Courses':Course.query.count()}
    return render_template('generic.html',title=title,subtitle=subtitle,module=title,items=items,kind=kind,slug=slug,stats=stats,allowed_roles=sorted(MODULE_ROLE_RULES.get(slug, {'All authenticated users'})),can_create=(slug not in MODULE_ROLE_RULES or current_user.role in MODULE_ROLE_RULES[slug]))

# Keep endpoint names expected by the existing sidebar.
for slug in GENERIC:
    endpoint='generic_'+slug.replace('-','_')
    app.add_url_rule('/portal/'+slug, endpoint, generic_portal, defaults={'slug':slug}, methods=['GET','POST'])

# aliases that point to real student/industry/faculty/admin pages
# ---------- API ----------
@app.route('/admin/learning-verification', methods=['GET','POST'])
@role_required('Platform Admin','Super Admin','Institution Admin')
def learning_verification():
    if request.method=='POST':
        eid=int(request.form.get('enrollment_id',0)); decision=request.form.get('decision')
        e=db.session.get(LearningEnrollment,eid)
        if not e: abort(404)
        if decision=='approve': e.status='Approved'; e.verified_by=current_user.id; e.verified_at=datetime.utcnow(); notify(e.student.user_id,'Learning enrollment approved',f'Your {e.resource_type.upper()} enrollment has been approved.','learning'); flash('Enrollment approved.','success')
        elif decision=='reject': e.status='Rejected'; e.verified_by=current_user.id; e.verified_at=datetime.utcnow(); notify(e.student.user_id,'Learning enrollment rejected',f'Your {e.resource_type.upper()} enrollment was rejected.','learning'); flash('Enrollment rejected.','warning')
        audit('Learning verification',f'Enrollment #{eid} {decision}'); db.session.commit(); return redirect(url_for('learning_verification'))
    pending=LearningEnrollment.query.filter(LearningEnrollment.status=='Pending Verification').order_by(LearningEnrollment.created_at.desc()).all()
    titles={}
    for e in pending:
        if e.resource_type=='course':
            obj=db.session.get(Course,e.resource_id); titles[e.id]=obj.title if obj else 'Course'
        else:
            obj=db.session.get(Opportunity,e.resource_id); titles[e.id]=obj.title if obj else 'Program'
    return render_template('learning_verification.html',items=pending,titles=titles)

@app.route('/ai-chat', methods=['GET','POST'])
@login_required
def ai_chat():
    if request.method=='POST':
        message=request.form.get('message','').strip()
        if not message: return jsonify({'reply':'Please enter a question.'})
        api_key=os.getenv('GEMINI_API_KEY','').strip()
        if api_key:
            try:
                import requests
                model=os.getenv('GEMINI_MODEL','gemini-2.5-flash')
                context=f"User role: {current_user.role}. User: {current_user.name}. Answer as an assistant for an Academia-Industry Collaboration Portal. Help with courses, FDPs, skills, applications, profiles, internships, mentorship, and portal navigation. Never reveal private records or secrets. User question: {message}"
                r=requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',json={'contents':[{'parts':[{'text':context}]}]},timeout=20); r.raise_for_status(); data=r.json(); reply=data['candidates'][0]['content']['parts'][0]['text']
                return jsonify({'reply':reply,'provider':'Academia Assistant'})
            except Exception:
                pass
        lower=message.lower()
        answers=[('course','Open Courses, choose a course, submit enrollment, wait for verification, then record attendance and progress until completion.'),('fdp','Open FDPs, select a published program and apply. Your application goes to authorized verification before attendance.'),('certificate','Open Certifications to add your credential, upload evidence and request verification.'),('profile','Click your profile photo in the top-right corner to open My Profile and upload or change your photo.'),('application','Open Applications to track Submitted, Under Review, Shortlisted, Assessment, Interview, Selected or Rejected stages.'),('skill','Use Skill Profile, Skill Gap and AI Recommendations to identify missing skills and recommended learning.'),('otp','Email and phone verification use OTP during registration when configured in .env.')];
        for key,reply in answers:
            if key in lower: return jsonify({'reply':reply,'provider':'Portal AI Assistant'})
        return jsonify({'reply':'I can help with courses, FDPs, certifications, skills, applications, profile, mentorship and portal navigation. For full conversational AI, add GEMINI_API_KEY to your .env file.','provider':'Portal AI Assistant'})
    return render_template('ai_chat.html',title='AI Chatbot')

@app.route('/api/recommendations')
@role_required('Student')
def api_recommendations():
    return jsonify([{'opportunity_id':o.id,'title':o.title,'company':o.company.name,'match':score,'reasons':why} for score,o,why in ai_recommendations(current_user.student,10)])

@app.route('/api/ai-explain/<int:oid>')
@role_required('Student')
def ai_explain(oid):
    o=db.get_or_404(Opportunity,oid); score,why=student_match(current_user.student,o)
    api_key=os.getenv('GEMINI_API_KEY','').strip()
    if not api_key:
        return jsonify({'provider':'transparent-rule-engine','match':score,'explanation':why,'message':'Set GEMINI_API_KEY in .env to enable Gemini-generated explanations.'})
    try:
        import requests
        model=os.getenv('GEMINI_MODEL','gemini-2.5-flash')
        prompt=f"Explain this career recommendation concisely. Match score {score}%. Opportunity: {o.title}. Required skills: {[x.skill.name for x in o.skills]}. Student skills: {[x.skill.name+':'+str(x.level) for x in current_user.student.skills]}. Reasons: {why}. Give 3 strengths and 2 next actions."
        r=requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}',json={'contents':[{'parts':[{'text':prompt}]}]},timeout=15)
        r.raise_for_status(); data=r.json(); text=data['candidates'][0]['content']['parts'][0]['text']
        return jsonify({'provider':'gemini','match':score,'explanation':text})
    except Exception as exc:
        return jsonify({'provider':'transparent-rule-engine','match':score,'explanation':why,'message':'Gemini was unavailable; showing deterministic recommendation logic.','detail':str(exc)[:120]})

@app.route('/api/notifications')
@login_required
def api_notifications(): return jsonify([{'id':n.id,'title':n.title,'body':n.body,'read':n.read} for n in Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(20)])
@app.route('/healthz')
def healthz():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status':'ok','database':'ok'}), 200
    except Exception:
        return jsonify({'status':'degraded','database':'unavailable'}), 503

@app.errorhandler(403)
def forbidden(e): return render_template('403.html'),403
@app.errorhandler(404)
def not_found(e): return render_template('404.html'),404

# ---------- Seed ----------
def seed():
    if User.query.first(): return
    insts=[Institution(name='National Institute of Technology Demo',city='Ahmedabad'),Institution(name='State Technical University Demo',city='Surat'),Institution(name='Institute of Management & Technology Demo',city='Vadodara')]
    db.session.add_all(insts); db.session.flush()
    skills_data=[('Python','Programming'),('SQL','Data'),('JavaScript','Programming'),('React','Web'),('Flask','Web'),('Machine Learning','AI'),('Data Analysis','Data'),('Cloud Computing','Cloud'),('Communication','Soft Skill'),('Leadership','Soft Skill'),('Git','Tools'),('Docker','Cloud'),('Cyber Security','Security'),('UI/UX','Design'),('Project Management','Management'),('Java','Programming'),('C++','Programming'),('Power BI','Data'),('NLP','AI'),('Prompt Engineering','AI')]
    skills=[]
    for n,c in skills_data: skills.append(Skill(name=n,category=c,level='Intermediate'))
    db.session.add_all(skills); db.session.flush()
    roles=[]
    role_specs={'Full Stack Developer':['Python','JavaScript','React','SQL','Git','Flask'],'Data Analyst':['SQL','Data Analysis','Power BI','Python','Communication'],'AI/ML Engineer':['Python','Machine Learning','NLP','SQL','Docker'],'Cloud Engineer':['Python','Cloud Computing','Docker','Git'],'Product Designer':['UI/UX','Communication','Leadership']}
    for name, names in role_specs.items():
        r=CareerRole(name=name,domain='Technology',description=f'Career roadmap for {name}.'); db.session.add(r); db.session.flush()
        for sn in names: db.session.add(RoleSkill(role_id=r.id,skill_id=Skill.query.filter_by(name=sn).first().id,required_level=3))
        roles.append(r)
    companies=[]
    for i in range(10):
        c=Company(name=f'Demo Industry {i+1}',industry=['IT Services','FinTech','HealthTech','Manufacturing'][i%4],email=f'hr{i+1}@demoindustry.com',location=['Ahmedabad','Surat','Vadodara','Pune'][i%4],size='100-500',description='Fictional competition demo company.',verification_status='Approved'); db.session.add(c); companies.append(c)
    db.session.flush()
    for c in companies:
        for sn in role_specs['Full Stack Developer'][:3]: db.session.add(CompanySkill(company_id=c.id,skill_id=Skill.query.filter_by(name=sn).first().id,priority='High',level=3))
    users=[]
    demo=[('student@demo.com','Demo Student','Student'),('faculty@demo.com','Dr. Demo Faculty','Faculty'),('industry@demo.com','Demo Recruiter','Industry'),('admin@demo.com','Platform Admin','Platform Admin'),('superadmin@demo.com','Super Administrator','Super Admin')]
    for email,name,role in demo:
        u=User(name=name,email=email,password_hash=generate_password_hash('demo123'),role=role,email_verified=True,phone_verified=True,phone='+919999999999'); db.session.add(u); db.session.flush(); users.append(u)
    s=StudentProfile(user_id=users[0].id,institution=insts[0].name,department='Computer Engineering',program='B.Tech',semester='6',graduation_year=2027,location='Ahmedabad',desired_role='Full Stack Developer',bio='Demo student with an evolving verified skill profile.')
    db.session.add(s); db.session.flush()
    for sn,lvl in [('Python',4),('SQL',3),('JavaScript',3),('Git',4),('Communication',3)]: db.session.add(StudentSkill(student_id=s.id,skill_id=Skill.query.filter_by(name=sn).first().id,level=lvl,verified=True))
    f=FacultyProfile(user_id=users[1].id,institution=insts[0].name,department='Computer Engineering',designation='Associate Professor',qualifications='PhD, M.Tech',experience='12 years',expertise='AI, Software Engineering, Industry 4.0',research='Applied AI and skill analytics'); db.session.add(f)
    db.session.add(CompanyUser(user_id=users[2].id,company_id=companies[0].id,title='Talent Acquisition Manager'))
    for i in range(19):
        u=User(name=f'Demo Student {i+2}',email=f'student{i+2}@demo.com',password_hash=generate_password_hash('demo123'),role='Student',email_verified=True,phone_verified=True,phone='+919999999999'); db.session.add(u); db.session.flush(); sp=StudentProfile(user_id=u.id,institution=insts[i%3].name,department='Computer Engineering',program='B.Tech',semester=str(2+(i%6)),graduation_year=2027+(i%2),location=['Ahmedabad','Surat','Vadodara'][i%3],desired_role=list(role_specs)[i%len(role_specs)],bio='Fictional seeded student for demonstration.'); db.session.add(sp); db.session.flush()
        for sn in role_specs[sp.desired_role][:3]: db.session.add(StudentSkill(student_id=sp.id,skill_id=Skill.query.filter_by(name=sn).first().id,level=2+(i%3),verified=(i%2==0)))
    for i,c in enumerate(companies):
        r=list(role_specs.values())[i%len(role_specs)]; o=Opportunity(company_id=c.id,type=['Internship','Job','Apprenticeship','Live Project'][i%4],title=f'{r[0]} Opportunity {i+1}',description='Realistic fictional opportunity for the demo journey.',eligibility='Relevant degree/program; portfolio preferred.',openings=2,location=c.location,mode=['Hybrid','On-site','Remote'][i%3],duration='8-12 weeks',compensation='₹15,000/month' if i%2==0 else 'Competitive',deadline=datetime.utcnow()+timedelta(days=15+i),status='Published'); db.session.add(o); db.session.flush()
        for sn in r[:4]: db.session.add(OpportunitySkill(opportunity_id=o.id,skill_id=Skill.query.filter_by(name=sn).first().id,required_level=3))
    fdp_titles=['AI in Education','Modern Cloud Practice','Applied Data Analytics','Cyber Security Readiness']
    for i in range(4):
        c=companies[i]; o=Opportunity(company_id=c.id,type='FDP',title=f'Industry FDP: {fdp_titles[i]}',description='Faculty/student development program with guided sessions, attendance and completion tracking.',eligibility='Open to eligible registered learners.',openings=40,location=c.location,mode=['Online','Hybrid'][i%2],duration='5 days',compensation='Sponsored',deadline=datetime.utcnow()+timedelta(days=20+i),status='Published'); db.session.add(o)
    for i in range(20):
        sn=skills[i%len(skills)].name; db.session.add(Course(title=f'Practical {sn} Masterclass',provider=['AIC Learning Lab','Industry Academy'][i%2],level=['Beginner','Intermediate','Advanced'][i%3],duration='4 weeks',description=f'Hands-on learning path covering {sn}.',skill_id=skills[i%len(skills)].id))
    for i in range(10): db.session.add(Event(title=f'Industry-Academia Event {i+1}',event_type=['Workshop','Guest Lecture','FDP','Challenge'][i%4],event_date=datetime.utcnow()+timedelta(days=i+1),location=['Online','Ahmedabad','Surat'][i%3],description='Fictional event for competition demonstration.'))
    for i in range(10): db.session.add(Mentorship(title=f'Mentorship Track {i+1}',mentor=f'Industry Mentor {i+1}',domain=['AI','Web','Data','Cloud'][i%4],seats=10,status='Open'))
    # Seed linked records for the previously shell-only modules. These are shared database rows, not hardcoded UI cards.
    module_seed = {
        'career-roadmap': [('Full Stack Roadmap','6-step path from profile to job readiness.','Technology')],
        'innovation-challenges': [('Smart Campus Challenge','Build an AI-powered solution for campus operations.','AI Challenge'),('Green Tech Challenge','Prototype a measurable sustainability solution.','Sustainability')],
        'training-programs': [('Industry Python Bootcamp','Hands-on Python, APIs and testing for entry-level talent.','Technical Training')],
        'certification-programs': [('AIC Applied Data Certificate','Project-based certificate covering SQL, analysis and dashboards.','Certification')],
        'skill-assessments': [('Industry Readiness Assessment','Scenario-based assessment for technical and communication skills.','Assessment')],
        'research': [('Applied AI Skill Analytics','Industry-academia research collaboration on skill readiness.','Research')],
        'industry-projects': [('AI Talent Matching Pilot','Collaborative project to improve transparent skill matching.','Research & Project')],
        'workshops-guest-lectures': [('Industry Hiring Masterclass','Recruiters explain portfolio and interview expectations.','Guest Lecture')],
        'policies': [('Privacy & Consent Policy','Profile discovery and protected document access rules.','Governance')],
        'announcements': [('AIC Portal Launch','The competition-ready interconnected portal is now live.','Platform')],
        'integrations': [('Learning Provider Adapter','Demo integration interface for future external learning providers.','Demo Integration')],
        'system-config': [('Notification Engine','Controls platform notification behavior.','Configuration')],
        'institutional-access': [('Institution Scoped Access','Demo institution access configuration.','Access')],
        'industry-categories': [('Technology','IT, software, data and AI companies.','Category'),('Manufacturing','Industrial and engineering organizations.','Category')],
        'data-management': [('Database Health Check','Shared relational records and indexes are operational.','Operations')],
        'moderation': [('Opportunity Content Review','Review submitted opportunity descriptions and eligibility.','Moderation')],
        'verification-center': [('Company Verification Queue','Review company identity and authorization status.','Verification')],
    }
    for module, rows in module_seed.items():
        if not ModuleRecord.query.filter_by(module=module).first():
            for title, desc, cat in rows:
                db.session.add(ModuleRecord(module=module,title=title,description=desc,category=cat,status='Active',owner_id=users[3].id))
    # Seed a real cross-role message and a mentorship request for the demo journey.
    db.session.add(Message(sender_id=users[1].id, recipient_id=users[0].id, subject='Welcome to mentorship', body='Review your skill gap and let us discuss your next learning actions.'))
    db.session.add(MentorshipRequest(mentorship_id=1, student_id=users[0].student.id, status='Accepted', note='Focus on full-stack readiness.'))
    # Real assessment question bank: multiple questions per skill so attempts can be randomized.
    qdata={'Python': [('What does len([1,2,3]) return?', ['2', '3', '4', '1'], 1), ('Which keyword defines a function in Python?', ['func', 'define', 'def', 'function'], 2), ('What is the output of 2 ** 3?', ['6', '8', '9', '5'], 1), ('Which data type stores key-value pairs?', ['list', 'tuple', 'dict', 'set'], 2), ('Which statement handles exceptions?', ['try/except', 'if/else', 'for/in', 'with/as'], 0)], 'SQL': [('Which clause filters rows?', ['ORDER BY', 'WHERE', 'GROUP BY', 'SELECT'], 1), ('Which command adds new rows?', ['UPDATE', 'ALTER', 'INSERT', 'MERGE'], 2), ('Which function counts rows?', ['SUM()', 'COUNT()', 'TOTAL()', 'ROWS()'], 1), ('Which keyword removes duplicate results?', ['UNIQUE', 'DISTINCT', 'ONLY', 'DIFFERENT'], 1), ('Which join returns matching rows from both tables?', ['INNER JOIN', 'LEFT JOIN', 'CROSS JOIN', 'FULL TEXT'], 0)], 'JavaScript': [('Which keyword declares a block-scoped variable?', ['var', 'let', 'define', 'dim'], 1), ('Which method converts JSON text to an object?', ['JSON.parse()', 'JSON.object()', 'JSON.read()', 'JSON.decodeText()'], 0), ('What does === check?', ['Only value', 'Only type', 'Value and type', 'Reference only'], 2), ('Which symbol starts a single-line comment?', ['<!--', '//', '##', '**'], 1), ('Which array method adds an item to the end?', ['pop()', 'shift()', 'push()', 'join()'], 2)], 'React': [('Which hook stores local component state?', ['useState', 'useRoute', 'useFetch', 'useStyle'], 0), ('JSX is primarily used to?', ['Write SQL', 'Describe UI in JavaScript', 'Create databases', 'Style Python'], 1), ('Props are generally?', ['Mutable by child', 'Inputs passed to a component', 'Database rows', 'CSS files'], 1), ('Which hook runs side effects?', ['useMemo', 'useEffect', 'useState', 'useRef'], 1), ('A React key helps identify?', ['CSS colors', 'List elements', 'API keys', 'Routes only'], 1)], 'Flask': [('Flask is a Python framework mainly used for?', ['Web applications', 'Image editing', 'Operating systems', 'Spreadsheets'], 0), ('Which object represents the current request?', ['request', 'response', 'session_db', 'query'], 0), ('Which decorator defines a route?', ['@app.route', '@route.app', '@flask.url', '@path'], 0), ('Jinja templates are normally rendered with?', ['render_template', 'render_page', 'template_show', 'html_render'], 0), ('Which file commonly stores Flask configuration in this project?', ['.env', 'package.json', 'pom.xml', 'composer.json'], 0)], 'Machine Learning': [('What is supervised learning trained with?', ['Only unlabeled data', 'Labeled data', 'No data', 'Passwords'], 1), ('Which metric is common for classification?', ['Accuracy', 'Disk size', 'Latency only', 'File count'], 0), ('Overfitting means a model?', ['Generalizes perfectly', 'Fits training data too closely', 'Has no parameters', 'Cannot train'], 1), ('A feature is typically?', ['An input variable', 'A password', 'A server', 'A database'], 0), ('Which split evaluates unseen data?', ['Training set', 'Test set', 'Cache set', 'Schema set'], 1)], 'Data Analysis': [('Which measure is the middle value?', ['Mean', 'Median', 'Mode', 'Range'], 1), ('A bar chart is useful for?', ['Comparing categories', 'Encrypting files', 'Routing traffic', 'Compiling code'], 0), ('Missing values are often called?', ['Nulls', 'Indexes', 'Schemas', 'Joins'], 0), ('Correlation measures?', ['Association between variables', 'File size', 'CPU speed', 'Password strength'], 0), ('Which is a tabular data tool in Python?', ['pandas', 'Flask', 'pytest', 'Jinja'], 0)], 'Git': [('Which command creates a local Git repository?', ['git init', 'git start', 'git create', 'git new'], 0), ('Which command records staged changes?', ['git save', 'git commit', 'git pushall', 'git record'], 1), ('Which command downloads remote changes?', ['git pull', 'git copy', 'git fetchallonly', 'git receive'], 0), ('Which command shows working-tree changes?', ['git status', 'git inspect', 'git changes', 'git tree'], 0), ('Which command creates a branch?', ['git branch', 'git fork', 'git line', 'git split'], 0)], 'Communication': [('Active listening means?', ['Interrupting often', 'Understanding before responding', 'Ignoring feedback', 'Speaking only'], 1), ('Good professional communication should be?', ['Clear and respectful', 'Always lengthy', 'Vague', 'Aggressive'], 0), ('Constructive feedback should focus on?', ['The person personally', 'Specific behavior and improvement', 'Rumors', 'Unrelated issues'], 1), ('Which helps resolve misunderstandings?', ['Clarifying questions', 'Silence', 'Guessing', 'Blaming'], 0), ('An effective presentation should have?', ['A clear structure', 'No conclusion', 'Only text', 'No audience consideration'], 0)]}
    for skill_name, rows in qdata.items():
        skill=Skill.query.filter_by(name=skill_name).first()
        if skill and not AssessmentQuestion.query.filter_by(skill_id=skill.id).first():
            for question, options, correct in rows:
                db.session.add(AssessmentQuestion(skill_id=skill.id,question=question,options_json=json.dumps(options),correct_index=correct,explanation='Review the related skill topic if you missed this question.'))

    weights={'skill_weight':'40','eligibility_weight':'25','career_weight':'20','interest_weight':'15'}
    for k,v in weights.items(): db.session.add(Setting(key=k,value=v))
    notify(users[0].id,'Welcome','Explore your skill gap and AI recommendations.','welcome'); notify(users[1].id,'Faculty demo','You have authorized students available for guidance.','mentorship'); notify(users[2].id,'Recruitment demo','Your verified company can discover matching talent.','recruitment'); notify(users[3].id,'Admin demo','Pending governance actions are ready.','approval')
    db.session.commit()

def ensure_extension_seed():
    # Backfill the new module records when the application is upgraded over an older demo database.
    if not User.query.first(): return
    admin=User.query.filter(User.role.in_(['Platform Admin','Super Admin'])).first()
    if not admin: admin=User.query.first()
    module_seed={
      'career-roadmap':[('Full Stack Roadmap','Profile → assessment → gap → learning → opportunity → readiness.','Technology')],
      'innovation-challenges':[('Smart Campus Challenge','AI-powered campus operations problem statement.','AI Challenge')],
      'training-programs':[('Industry Python Bootcamp','Hands-on Python, APIs and testing.','Technical Training')],
      'certification-programs':[('AIC Applied Data Certificate','Project-based SQL, analysis and dashboard certificate.','Certification')],
      'skill-assessments':[('Industry Readiness Assessment','Technical and communication readiness assessment.','Assessment')],
      'research':[('Applied AI Skill Analytics','Industry-academia research collaboration.','Research')],
      'industry-projects':[('AI Talent Matching Pilot','Collaborative transparent matching project.','Project')],
      'workshops-guest-lectures':[('Industry Hiring Masterclass','Recruiter-led portfolio and interview workshop.','Guest Lecture')],
      'policies':[('Privacy & Consent Policy','Rules for profile visibility and protected data access.','Governance')],
      'announcements':[('AIC Portal Update','New connected workflow modules are available.','Platform')],
      'integrations':[('Learning Provider Adapter','Demo interface for future external providers.','Integration')],
      'system-config':[('Notification Engine','Platform notification configuration.','Configuration')],
      'moderation':[('Opportunity Content Review','Review submitted opportunity content.','Moderation')],
      'verification-center':[('Company Verification Queue','Review company verification status.','Verification')],
    }
    changed=False
    if not Opportunity.query.filter_by(type='FDP').first():
        companies=Company.query.filter_by(verification_status='Approved').limit(4).all()
        fdp_titles=['AI in Education','Modern Cloud Practice','Applied Data Analytics','Cyber Security Readiness']
        for i,c in enumerate(companies):
            db.session.add(Opportunity(company_id=c.id,type='FDP',title=f'Industry FDP: {fdp_titles[i]}',description='Faculty/student development program with guided sessions, attendance and completion tracking.',eligibility='Open to eligible registered learners.',openings=40,location=c.location,mode=['Online','Hybrid'][i%2],duration='5 days',compensation='Sponsored',deadline=datetime.utcnow()+timedelta(days=20+i),status='Published')); changed=True
    for module,rows in module_seed.items():
        if not ModuleRecord.query.filter_by(module=module).first():
            for title,desc,cat in rows:
                db.session.add(ModuleRecord(module=module,title=title,description=desc,category=cat,status='Active',owner_id=admin.id)); changed=True
    # Backfill assessment questions for upgraded databases.
    qdata={'Python': [('What does len([1,2,3]) return?', ['2', '3', '4', '1'], 1), ('Which keyword defines a function in Python?', ['func', 'define', 'def', 'function'], 2), ('What is the output of 2 ** 3?', ['6', '8', '9', '5'], 1), ('Which data type stores key-value pairs?', ['list', 'tuple', 'dict', 'set'], 2), ('Which statement handles exceptions?', ['try/except', 'if/else', 'for/in', 'with/as'], 0)], 'SQL': [('Which clause filters rows?', ['ORDER BY', 'WHERE', 'GROUP BY', 'SELECT'], 1), ('Which command adds new rows?', ['UPDATE', 'ALTER', 'INSERT', 'MERGE'], 2), ('Which function counts rows?', ['SUM()', 'COUNT()', 'TOTAL()', 'ROWS()'], 1), ('Which keyword removes duplicate results?', ['UNIQUE', 'DISTINCT', 'ONLY', 'DIFFERENT'], 1), ('Which join returns matching rows from both tables?', ['INNER JOIN', 'LEFT JOIN', 'CROSS JOIN', 'FULL TEXT'], 0)], 'JavaScript': [('Which keyword declares a block-scoped variable?', ['var', 'let', 'define', 'dim'], 1), ('Which method converts JSON text to an object?', ['JSON.parse()', 'JSON.object()', 'JSON.read()', 'JSON.decodeText()'], 0), ('What does === check?', ['Only value', 'Only type', 'Value and type', 'Reference only'], 2), ('Which symbol starts a single-line comment?', ['<!--', '//', '##', '**'], 1), ('Which array method adds an item to the end?', ['pop()', 'shift()', 'push()', 'join()'], 2)], 'React': [('Which hook stores local component state?', ['useState', 'useRoute', 'useFetch', 'useStyle'], 0), ('JSX is primarily used to?', ['Write SQL', 'Describe UI in JavaScript', 'Create databases', 'Style Python'], 1), ('Props are generally?', ['Mutable by child', 'Inputs passed to a component', 'Database rows', 'CSS files'], 1), ('Which hook runs side effects?', ['useMemo', 'useEffect', 'useState', 'useRef'], 1), ('A React key helps identify?', ['CSS colors', 'List elements', 'API keys', 'Routes only'], 1)], 'Flask': [('Flask is a Python framework mainly used for?', ['Web applications', 'Image editing', 'Operating systems', 'Spreadsheets'], 0), ('Which object represents the current request?', ['request', 'response', 'session_db', 'query'], 0), ('Which decorator defines a route?', ['@app.route', '@route.app', '@flask.url', '@path'], 0), ('Jinja templates are normally rendered with?', ['render_template', 'render_page', 'template_show', 'html_render'], 0), ('Which file commonly stores Flask configuration in this project?', ['.env', 'package.json', 'pom.xml', 'composer.json'], 0)], 'Machine Learning': [('What is supervised learning trained with?', ['Only unlabeled data', 'Labeled data', 'No data', 'Passwords'], 1), ('Which metric is common for classification?', ['Accuracy', 'Disk size', 'Latency only', 'File count'], 0), ('Overfitting means a model?', ['Generalizes perfectly', 'Fits training data too closely', 'Has no parameters', 'Cannot train'], 1), ('A feature is typically?', ['An input variable', 'A password', 'A server', 'A database'], 0), ('Which split evaluates unseen data?', ['Training set', 'Test set', 'Cache set', 'Schema set'], 1)], 'Data Analysis': [('Which measure is the middle value?', ['Mean', 'Median', 'Mode', 'Range'], 1), ('A bar chart is useful for?', ['Comparing categories', 'Encrypting files', 'Routing traffic', 'Compiling code'], 0), ('Missing values are often called?', ['Nulls', 'Indexes', 'Schemas', 'Joins'], 0), ('Correlation measures?', ['Association between variables', 'File size', 'CPU speed', 'Password strength'], 0), ('Which is a tabular data tool in Python?', ['pandas', 'Flask', 'pytest', 'Jinja'], 0)], 'Git': [('Which command creates a local Git repository?', ['git init', 'git start', 'git create', 'git new'], 0), ('Which command records staged changes?', ['git save', 'git commit', 'git pushall', 'git record'], 1), ('Which command downloads remote changes?', ['git pull', 'git copy', 'git fetchallonly', 'git receive'], 0), ('Which command shows working-tree changes?', ['git status', 'git inspect', 'git changes', 'git tree'], 0), ('Which command creates a branch?', ['git branch', 'git fork', 'git line', 'git split'], 0)], 'Communication': [('Active listening means?', ['Interrupting often', 'Understanding before responding', 'Ignoring feedback', 'Speaking only'], 1), ('Good professional communication should be?', ['Clear and respectful', 'Always lengthy', 'Vague', 'Aggressive'], 0), ('Constructive feedback should focus on?', ['The person personally', 'Specific behavior and improvement', 'Rumors', 'Unrelated issues'], 1), ('Which helps resolve misunderstandings?', ['Clarifying questions', 'Silence', 'Guessing', 'Blaming'], 0), ('An effective presentation should have?', ['A clear structure', 'No conclusion', 'Only text', 'No audience consideration'], 0)]}
    for skill_name, rows in qdata.items():
        skill=Skill.query.filter_by(name=skill_name).first()
        if skill and not AssessmentQuestion.query.filter_by(skill_id=skill.id).first():
            for question, options, correct in rows:
                db.session.add(AssessmentQuestion(skill_id=skill.id,question=question,options_json=json.dumps(options),correct_index=correct,explanation='Review the related skill topic if you missed this question.'))
            changed=True

    if changed: db.session.commit()

def migrate_legacy_schema():
    # SQLite create_all does not add columns to existing tables; safely add the OTP fields on upgrades.
    from sqlalchemy import inspect
    inspector=inspect(db.engine)
    if 'user' in inspector.get_table_names():
        cols={c['name'] for c in inspector.get_columns('user')}
        additions={'email_verified':'BOOLEAN DEFAULT 0','phone_verified':'BOOLEAN DEFAULT 0','phone':'VARCHAR(30)'}
        for name,typ in additions.items():
            if name not in cols:
                db.session.execute(text(f'ALTER TABLE user ADD COLUMN {name} {typ}'))
        db.session.commit()

with app.app_context():
    db.create_all(); migrate_legacy_schema(); db.create_all(); seed(); ensure_extension_seed()

if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','5000')), debug=os.getenv('FLASK_DEBUG','0')=='1')
