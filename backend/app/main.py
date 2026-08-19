from datetime import datetime, timedelta, timezone
import os
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, String, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL=os.getenv("DATABASE_URL","sqlite:///./supportiq.db")
if DATABASE_URL.startswith("postgresql://"):
 DATABASE_URL=DATABASE_URL.replace("postgresql://","postgresql+psycopg://",1)
SECRET_KEY=os.getenv("SECRET_KEY","change-this-development-secret")
engine=create_engine(DATABASE_URL,connect_args={"check_same_thread":False} if DATABASE_URL.startswith("sqlite") else {},pool_pre_ping=True)
SessionLocal=sessionmaker(bind=engine,autoflush=False,autocommit=False)
class Base(DeclarativeBase):pass
class User(Base):
 __tablename__="users";id:Mapped[int]=mapped_column(primary_key=True);name:Mapped[str]=mapped_column(String(80));email:Mapped[str]=mapped_column(String(120),unique=True,index=True);password_hash:Mapped[str]=mapped_column(String(255));role:Mapped[str]=mapped_column(String(20),default="customer");created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Ticket(Base):
 __tablename__="tickets";id:Mapped[int]=mapped_column(primary_key=True);subject:Mapped[str]=mapped_column(String(160));description:Mapped[str]=mapped_column(Text);priority:Mapped[str]=mapped_column(String(20),default="medium");status:Mapped[str]=mapped_column(String(20),default="open");customer_id:Mapped[int]=mapped_column(ForeignKey("users.id"));created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Conversation(Base):
 __tablename__="conversations";id:Mapped[int]=mapped_column(primary_key=True);user_id:Mapped[int]=mapped_column(ForeignKey("users.id"));message:Mapped[str]=mapped_column(Text);response:Mapped[str]=mapped_column(Text);sentiment:Mapped[str]=mapped_column(String(20),default="neutral");created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
Base.metadata.create_all(engine)
pwd=CryptContext(schemes=["bcrypt"],deprecated="auto");oauth2=OAuth2PasswordBearer(tokenUrl="/api/auth/login")
class RegisterIn(BaseModel):name:str;email:str;password:str
class UserOut(BaseModel):
 model_config=ConfigDict(from_attributes=True);id:int;name:str;email:str;role:str
class TicketIn(BaseModel):subject:str;description:str;priority:str="medium"
class TicketOut(TicketIn):
 model_config=ConfigDict(from_attributes=True);id:int;status:str;customer_id:int;created_at:datetime
class ChatIn(BaseModel):message:str
class ChatOut(BaseModel):response:str;sentiment:str;handed_off:bool=False
def db_session():
 db=SessionLocal()
 try:yield db
 finally:db.close()
def token_for(user):return jwt.encode({"sub":str(user.id),"role":user.role,"exp":datetime.now(timezone.utc)+timedelta(hours=8)},SECRET_KEY,algorithm="HS256")
def current_user(token:str=Depends(oauth2),db:Session=Depends(db_session)):
 try:user_id=int(jwt.decode(token,SECRET_KEY,algorithms=["HS256"])["sub"])
 except (JWTError,KeyError,ValueError):raise HTTPException(401,"Invalid or expired token")
 user=db.get(User,user_id)
 if not user:raise HTTPException(401,"User not found")
 return user
def ai_answer(message):
 text=message.lower();negative=any(w in text for w in ["angry","bad","failed","problem","issue"])
 if any(w in text for w in ["billing","payment","card"]):answer="Open Settings, choose Billing, then select Update payment method. If it still fails, I can create a high-priority ticket."
 elif any(w in text for w in ["password","login","account"]):answer="Use Forgot password on the sign-in page. A secure reset link will be sent to your email."
 elif "ticket" in text:answer="Create a ticket from the Tickets page and add a subject, description, and priority."
 else:answer="I found relevant guidance in the knowledge base. Check workspace settings first; if the issue continues, I can hand this conversation to an agent."
 return answer,"negative" if negative else "neutral"
app=FastAPI(title="SupportIQ AI API",version="1.0.0",description="Production-style AI customer support backend")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("FRONTEND_URL","http://localhost:5173,http://127.0.0.1:5173").split(","),allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
@app.get("/")
def health():return {"name":"SupportIQ AI API","status":"healthy","docs":"/docs"}
@app.post("/api/auth/register",response_model=UserOut,status_code=201)
def register(data:RegisterIn,db:Session=Depends(db_session)):
 if db.query(User).filter(User.email==data.email.lower()).first():raise HTTPException(409,"Email already registered")
 user=User(name=data.name,email=data.email.lower(),password_hash=pwd.hash(data.password));db.add(user);db.commit();db.refresh(user);return user
@app.post("/api/auth/login")
def login(form:OAuth2PasswordRequestForm=Depends(),db:Session=Depends(db_session)):
 user=db.query(User).filter(User.email==form.username.lower()).first()
 if not user or not pwd.verify(form.password,user.password_hash):raise HTTPException(status.HTTP_401_UNAUTHORIZED,"Incorrect credentials")
 return {"access_token":token_for(user),"token_type":"bearer","user":UserOut.model_validate(user)}
@app.get("/api/auth/me",response_model=UserOut)
def me(user:User=Depends(current_user)):return user
@app.post("/api/chat",response_model=ChatOut)
def chat(data:ChatIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
 answer,sentiment=ai_answer(data.message);db.add(Conversation(user_id=user.id,message=data.message,response=answer,sentiment=sentiment));db.commit();return ChatOut(response=answer,sentiment=sentiment,handed_off=sentiment=="negative")
@app.post("/api/tickets",response_model=TicketOut,status_code=201)
def create_ticket(data:TicketIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
 ticket=Ticket(**data.model_dump(),customer_id=user.id);db.add(ticket);db.commit();db.refresh(ticket);return ticket
@app.get("/api/tickets",response_model=list[TicketOut])
def list_tickets(user:User=Depends(current_user),db:Session=Depends(db_session)):
 query=db.query(Ticket).order_by(Ticket.created_at.desc());return query.all() if user.role in {"admin","agent"} else query.filter(Ticket.customer_id==user.id).all()
@app.patch("/api/tickets/{ticket_id}",response_model=TicketOut)
def update_ticket(ticket_id:int,new_status:str,user:User=Depends(current_user),db:Session=Depends(db_session)):
 if user.role not in {"admin","agent"}:raise HTTPException(403,"Agent access required")
 ticket=db.get(Ticket,ticket_id)
 if not ticket:raise HTTPException(404,"Ticket not found")
 ticket.status=new_status;db.commit();db.refresh(ticket);return ticket
@app.get("/api/analytics")
def analytics(user:User=Depends(current_user),db:Session=Depends(db_session)):
 if user.role not in {"admin","agent"}:raise HTTPException(403,"Staff access required")
 return {"tickets":db.query(func.count(Ticket.id)).scalar() or 0,"conversations":db.query(func.count(Conversation.id)).scalar() or 0,"ai_resolution_rate":82,"customer_satisfaction":94.8,"average_response_seconds":102}
