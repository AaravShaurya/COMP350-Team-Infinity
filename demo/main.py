# main.py

# Server Instructions:
# Run the server using:
# uvicorn main:app --reload
# Access the application at:
#   
# If you encounter an "address in use" error, find the PID using:
# lsof -i tcp:8000
# Then kill the process using:
# kill -9 <PID>
# If you face a "database locked" issue with SQLite, check if any process is using the database:
# lsof | grep easemyvote.db


from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import Base, SessionLocal, engine
from models import Voter, Vote, Candidate
from pydantic import EmailStr
from cryptography.fernet import Fernet
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature, BadTimeSignature
import os
import aiosmtplib
from email.message import EmailMessage
from jinja2 import Template
import datetime
from starlette.middleware.sessions import SessionMiddleware
import json
import logging
import httpx

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(_name_)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Initialize app and templates
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Create database tables
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Encryption key for voter anonymity
FERNET_KEY = os.getenv("FERNET_KEY")
if not FERNET_KEY:
    raise ValueError("FERNET_KEY environment variable is not set.")
fernet = Fernet(FERNET_KEY)

# Consistent secret key for session management and token serialization
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is not set.")
serializer = URLSafeTimedSerializer(SECRET_KEY)

# Add SessionMiddleware with correct parameters
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie='session',
    max_age=1800,
    https_only=False,
    same_site='lax',
)

# Email configuration (ensure sensitive info is stored securely)
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USERNAME = "easemyvote@gmail.com"
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
if not EMAIL_PASSWORD:
    raise ValueError("EMAIL_PASSWORD environment variable is not set.")

# Helper function to recalculate and update vote tallies
def recalculate_vote_tally(db: Session):
    """
    Recalculate and update the vote_tally for each candidate based on first preferences.
    """
    # Reset all vote tallies to 0
    db.query(Candidate).update({Candidate.vote_tally: 0})
    db.commit()

    # Fetch all votes
    votes = db.query(Vote).all()

    # Tally first preferences
    for vote in votes:
        preferences = json.loads(vote.preferences)
        first_pref = preferences.get('first_pref')
        if first_pref:
            candidate = db.query(Candidate).filter(Candidate.id == first_pref).first()
            if candidate:
                candidate.vote_tally += 1

    db.commit()
    logger.info("Vote tallies recalculated and updated.")

# Routes

@app.get("/", response_class=HTMLResponse)
def read_login(request: Request):
    return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": None})

@app.post("/login")
async def login(
    request: Request,
    email: EmailStr = Form(...),
    db: Session = Depends(get_db)
):
    email = email.lower().strip()  # Normalize email
    logger.info(f"Email entered: {email}")

    # Validate email
    if not all(component in email for component in ["sias", "krea.ac.in"]):
        logger.warning(f"Email validation failed for: {email}")
        return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "Unable to verify email."})

    # Check if voter exists
    voter = db.query(Voter).filter(Voter.email == email).first()
    if voter:
        # Check if voter has voted in the last 6 months
        if voter.has_voted:
            if voter.voted_at:
                six_months_ago = datetime.datetime.utcnow() - datetime.timedelta(days=180)
                if voter.voted_at >= six_months_ago:
                    logger.info(f"Voter {email} has already voted in the last 6 months.")
                    return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "You have already voted in the last 6 months."})
                else:
                    # Reset voter status
                    voter.has_voted = False
                    voter.is_verified = False
                    try:
                        db.commit()
                        logger.info(f"Voter {email} voting status reset.")
                    except Exception as e:
                        db.rollback()
                        logger.error(f"Database commit failed: {e}")
                        return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "Database error."})
            else:
                # If voted_at is None, reset voting status
                voter.has_voted = False
                voter.is_verified = False
                try:
                    db.commit()
                    logger.info(f"Voter {email} voting status reset.")
                except Exception as e:
                    db.rollback()
                    logger.error(f"Database commit failed: {e}")
                    return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "Database error."})
    else:
        logger.warning(f"Voter with email {email} does not exist in the database.")
        return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "Unable to verify email."})

    # Generate a token for email verification
    token = serializer.dumps(email, salt="email-confirm")

    # Create a verification link
    verification_link = f"http://127.0.0.1:8000/verify-email?token={token}"

    # Render the email template
    template_path = "verification_email.html"
    try:
        with open(os.path.join("templates", template_path)) as f:
            template = Template(f.read())
    except FileNotFoundError:
        logger.error(f"Email template '{template_path}' not found.")
        return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "Email template missing."})

    email_body = template.render(email=email, verification_link=verification_link)

    # Prepare the email message
    message = EmailMessage()
    message["From"] = EMAIL_USERNAME
    message["To"] = email
    message["Subject"] = "EaseMyVote Email Verification"
    message.set_content(email_body, subtype="html")

    # Send the verification email asynchronously
    try:
        await aiosmtplib.send(
            message,
            hostname=EMAIL_HOST,
            port=EMAIL_PORT,
            start_tls=True,
            username=EMAIL_USERNAME,
            password=EMAIL_PASSWORD,
        )
        logger.info(f"Verification email sent to {email}.")
    except Exception as e:
        logger.error(f"Email sending failed: {e}")
        return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "Unable to send verification email."})

    return templates.TemplateResponse("email_sent.html", {"request": request})

@app.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str, db: Session = Depends(get_db)):
    """
    Verifies the email of the user and prevents multiple voting by checking if they
    have already voted.

    Args:
        request (Request): The request object.
        token (str): The email verification token.
        db (Session): The database session.

    Returns:
        RedirectResponse: Redirects to the rules page if successful, or returns an error if invalid.
    """
    try:
        email = serializer.loads(token, salt="email-confirm", max_age=3600)
        logger.info(f"Email verified: {email}")
    except (SignatureExpired, BadSignature, BadTimeSignature) as e:
        logger.warning(f"Email verification failed: {e}")
        return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "The verification link is invalid or has expired."})

    # Fetch the voter from the database
    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        logger.warning(f"Voter with email {email} not found during verification.")
        return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "Unable to verify email."})

    # Check if the voter has already voted
    if voter.has_voted:
        logger.info(f"Voter {email} has already voted and cannot vote again.")
        return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "You have already voted and cannot vote again."})

    # Mark voter as verified
    voter.is_verified = True

    # Generate and store encrypted_voter_id if not already set
    if not voter.encrypted_id:
        encrypted_voter_id = fernet.encrypt(str(voter.id).encode()).decode()
        voter.encrypted_id = encrypted_voter_id

    try:
        db.commit()
        logger.info(f"Voter {email} has been verified.")
    except Exception as e:
        db.rollback()
        logger.error(f"Database commit failed: {e}")
        return templates.TemplateResponse("Login_EMV.html", {"request": request, "error": "Database error during verification."})

    # Store data in session
    request.session['user_email'] = email
    request.session['rules_read'] = False

    # Redirect to the rules page
    return RedirectResponse(url="/rules", status_code=303)

@app.get("/rules", response_class=HTMLResponse)
def show_rules(request: Request):
    email = request.session.get('user_email')
    if not email:
        logger.warning("No user_email in session. Redirecting to login.")
        return RedirectResponse(url="/")
    return templates.TemplateResponse("Rules_EMV.html", {"request": request})

@app.post("/rules")
def accept_rules(request: Request):
    email = request.session.get('user_email')
    if not email:
        logger.warning("No user_email in session during rules acceptance. Redirecting to login.")
        return RedirectResponse(url="/", status_code=303)

    request.session['rules_read'] = True
    logger.info(f"User {email} accepted the rules.")
    return RedirectResponse(url="/voting", status_code=303)

@app.get("/voting", response_class=HTMLResponse)
def show_voting_page(request: Request, db: Session = Depends(get_db)):
    """
    Displays the voting page. Allows access to users who have already voted if they are returning from the summary page.
    Args:
        request (Request): The request object.
        db (Session): The database session.
    Returns:
        HTMLResponse: Renders the voting page template.
    """
    email = request.session.get('user_email')
    rules_read = request.session.get('rules_read')

    if not email:
        logger.warning("No user_email in session when accessing voting page. Redirecting to login.")
        return RedirectResponse(url="/")
    if not rules_read:
        logger.info("Rules not accepted yet. Redirecting to rules page.")
        return RedirectResponse(url="/rules")

    # Fetch the voter from the database
    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        logger.warning(f"Voter with email {email} not found when accessing voting page.")
        return RedirectResponse(url="/")

    # Check if the voter has already voted, but allow them to go back and change their vote
    if voter.has_voted:
        # Allow the user to return to the voting page from the summary page to change their vote
        logger.info(f"Voter {email} is returning to the voting page to modify their vote.")
        # Note: We will allow access even if they have voted, so no error message is shown here.

    # Define the position to display
    position = "MOCC"

    try:
        candidates = db.query(Candidate).filter(func.lower(Candidate.position) == position.lower()).all()
    except Exception as e:
        logger.error(f"Error fetching candidates: {e}")
        raise HTTPException(status_code=500, detail="Error fetching candidates.")

    candidate_names = [candidate.name for candidate in candidates]
    logger.info(f"Candidates for position '{position}': {candidate_names}")

    return templates.TemplateResponse("Voting_EMV.html", {"request": request, "candidates": candidates, "position": position})

@app.post("/vote")
def submit_vote(
    request: Request,
    first_pref: int = Form(...),
    second_pref: int = Form(...),
    db: Session = Depends(get_db)
):
    """
    Submits or updates the user's vote. Allows users to change their vote if they return from the summary page.
    Args:
        request (Request): The request object.
        first_pref (int): The first preference candidate ID.
        second_pref (int): The second preference candidate ID.
        db (Session): The database session.
    Returns:
        RedirectResponse: Redirects to the summary page after submission.
    """
    email = request.session.get('user_email')
    if not email:
        logger.warning("Email missing in session during vote submission.")
        raise HTTPException(status_code=400, detail="Email missing")

    # Fetch the voter from the database
    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        logger.warning(f"Voter with email {email} not found during vote submission.")
        return templates.TemplateResponse(
            "Login_EMV.html", {"request": request, "error": "Unable to verify email."}
        )

    encrypted_voter_id = voter.encrypted_id

    # Check if a vote already exists for this voter
    existing_vote = db.query(Vote).filter(Vote.encrypted_voter_id == encrypted_voter_id).first()

    preferences = {
        "first_pref": first_pref,
        "second_pref": second_pref
    }

    try:
        if existing_vote:
            # Update the existing vote
            existing_vote.preferences = json.dumps(preferences)
            logger.info(f"Updated vote for voter {email}.")
        else:
            # Create a new vote
            vote = Vote(
                encrypted_voter_id=encrypted_voter_id,
                preferences=json.dumps(preferences)
            )
            db.add(vote)
            logger.info(f"Created new vote for voter {email}.")

        voter.has_voted = True
        voter.voted_at = datetime.datetime.utcnow()
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Database commit failed during vote submission: {e}")
        raise HTTPException(status_code=500, detail="Database error during vote submission.")

    # Recalculate and update vote tallies
    recalculate_vote_tally(db)

    logger.info(f"Vote submitted by {email}.")

    return RedirectResponse(url="/summary", status_code=303)

@app.get("/summary", response_class=HTMLResponse)
def show_summary(request: Request, db: Session = Depends(get_db)):
    email = request.session.get('user_email')
    if not email:
        logger.warning("No user_email in session when accessing summary page. Redirecting to login.")
        return RedirectResponse(url="/")

    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        logger.warning(f"Voter with email {email} not found when fetching summary.")
        return RedirectResponse(url="/")
    vote = db.query(Vote).filter(Vote.encrypted_voter_id == voter.encrypted_id).first()
    if not vote:
        logger.warning(f"Vote not found for voter {email} when fetching summary.")
        return RedirectResponse(url="/")
    preferences = json.loads(vote.preferences)

    first_pref_candidate = db.query(Candidate).filter(Candidate.id == preferences['first_pref']).first()
    second_pref_candidate = db.query(Candidate).filter(Candidate.id == preferences['second_pref']).first()

    preferences_display = {
        "first_pref": first_pref_candidate.name if first_pref_candidate else "N/A",
        "second_pref": second_pref_candidate.name if second_pref_candidate else "N/A"
    }

    logger.info(f"Summary for {email}: {preferences_display}")

    return templates.TemplateResponse("Summary_EMV.html", {"request": request, "preferences": preferences_display})

@app.get("/thankyou", response_class=HTMLResponse)
async def thank_you(request: Request, db: Session = Depends(get_db)):
    """
    Display the thank you page after the user has submitted their vote.
    Additionally, send a confirmation email to the voter confirming that their vote has been cast.

    Args:
        request (Request): FastAPI Request object.
        db (Session): Database session for retrieving user information.

    Returns:
        HTMLResponse: Renders the Thank You page template.
    """
    email = request.session.get('user_email')
    if not email:
        logger.warning("No user_email in session when accessing thank you page. Redirecting to login.")
        return RedirectResponse(url="/")

    # Send confirmation email
    subject = "EaseMyVote: Vote Confirmation"
    message = f"Dear voter, your vote has been successfully recorded. Thank you for voting in EaseMyVote!"

    email_message = EmailMessage()
    email_message["From"] = EMAIL_USERNAME
    email_message["To"] = email
    email_message["Subject"] = subject
    email_message.set_content(message)

    try:
        await aiosmtplib.send(
            email_message,
            hostname=EMAIL_HOST,
            port=EMAIL_PORT,
            start_tls=True,
            username=EMAIL_USERNAME,
            password=EMAIL_PASSWORD,
        )
        logger.info(f"Confirmation email sent to {email}.")
    except Exception as e:
        logger.error(f"Failed to send confirmation email: {e}")

    return templates.TemplateResponse("ThankYou_EMV.html", {"request": request})



# @app.get("/results", response_class=HTMLResponse)
# def get_results(request: Request, db: Session = Depends(get_db)):
#     votes = db.query(Vote).all()
#     all_preferences = [json.loads(vote.preferences) for vote in votes]

#     # Candidates list from the database
#     candidate_objs = db.query(Candidate).all()
#     candidates = {str(candidate.id): candidate.name for candidate in candidate_objs}
#     winner_id = instant_runoff_voting(all_preferences, list(candidates.keys()))
#     winner_name = candidates.get(str(winner_id), "No winner")

#     return templates.TemplateResponse("results.html", {"request": request, "winner": winner_name})

#@app.get("/runoff-voting/{position}")
#def run_off_voting(position: str, db: Session = Depends(get_db)):
   # winner = instant_runoff_voting(db, position)
   # return {"winner": winner}

# def instant_runoff_voting(db: Session, position: str):
#     candidates = db.query(Candidate).filter(Candidate.position == position).all()
#     candidate_ids = [str(candidate.id) for candidate in candidates]
#     candidate_names = {str(candidate.id): candidate.name for candidate in candidates}
    
#     votes = db.query(Vote).filter(Vote.preferences.isnot(None)).all()
#     vote_data = [json.loads(vote.preferences) for vote in votes]

#     rounds = []
#     round_number = 1
    
#     while True:
#         counts = defaultdict(int)
        
#         # Count votes based on first preferences
#         for vote in vote_data:
#             if 'first_pref' in vote and vote['first_pref'] in candidate_ids:
#                 counts[vote['first_pref']] += 1

#         total_votes = sum(counts.values())
#         round_info = {
#             "round": round_number,
#             "counts": {candidate_names[cid]: count for cid, count in counts.items()},
#         }
#         rounds.append(round_info)

#         # Check for a winner
#         for candidate_id, count in counts.items():
#             if count > total_votes / 2:
#                 round_info["winner"] = candidate_names[candidate_id]
#                 return {"rounds": rounds, "winner": candidate_names[candidate_id]}

#         if not counts:
#             return {"rounds": rounds, "winner": "No candidates left"}

#         # Eliminate candidate with the fewest votes
#         least_votes_candidate = min(counts, key=counts.get)
#         candidate_ids.remove(least_votes_candidate)
#         round_info["eliminated"] = candidate_names[least_votes_candidate]

#         # Remove eliminated candidate from votes and promote second preferences
#         for vote in vote_data:
#             if 'first_pref' in vote and vote['first_pref'] == least_votes_candidate:
#                 vote['first_pref'] = vote.get('second_pref', None)
#                 vote['second_pref'] = None

#         round_number += 1
        
#         if len(candidate_ids) == 1:
#             round_info["winner"] = candidate_names[candidate_ids[0]]
#             return {"rounds": rounds, "winner": candidate_names[candidate_ids[0]]}

    df = read_voter_data(excel_file_path)
    import_voters(df)
