from fastapi import FastAPI, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import Optional, List
import requests
import json
import os
import sys
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import models
from models import SubmissionSource, IssueStatus, UserSubmissionType
from database import engine, get_db

load_dotenv()
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:27b")

models.Base.metadata.create_all(bind=engine)

app = FastAPI(root_path="/api")

class IssueSubmissionItem(BaseModel):
    text: str = Field(..., min_length=1, description="The main text of the complaint or request.")
    submission_type_by_user: UserSubmissionType = Field(..., description="Type of submission indicated by user ('жалоба' or 'просьба').")
    source: SubmissionSource = Field(..., description="Source of the submission (e.g., 'telegram').")
    source_user_id: str = Field(..., description="User ID from the source platform (e.g., Telegram user ID).")
    source_username: Optional[str] = None
    user_first_name: Optional[str] = None

class LLMAnalysisResult(BaseModel):
    responsible_department: Optional[str] = None
    complaint_type: Optional[str] = None
    adress: Optional[str] = None
    applicant_data: Optional[str] = None
    other: Optional[str] = None

class SubmissionResponse(BaseModel):
    saved_record_id: int
    original_text: str
    submission_type_by_user: UserSubmissionType
    source: SubmissionSource
    source_user_id: str
    status: IssueStatus
    analysis: Optional[LLMAnalysisResult] = None
    llm_processing_error: Optional[str] = None
    message: str

class IssueDetails(BaseModel):
    id: int
    original_complaint: str
    submission_type_by_user: Optional[UserSubmissionType]
    source: SubmissionSource
    source_user_id: str
    source_username: Optional[str]
    user_first_name: Optional[str]
    responsible_department: Optional[str]
    complaint_type: Optional[str]
    address: Optional[str]
    status: IssueStatus
    llm_processing_error: Optional[str]
    created_at: datetime

    class Config:
        orm_mode = True



@app.post("/submit-issue/", response_model=SubmissionResponse)
def submit_issue(item: IssueSubmissionItem, db: Session = Depends(get_db)):
    llm_analysis_results = LLMAnalysisResult()
    llm_processing_error = None
    current_status = IssueStatus.NEW

    if item.submission_type_by_user == UserSubmissionType.COMPLAINT:
        prompt = f"""
Вы — высококвалифицированный эксперт в правительственном бюро, специализирующийся на маршрутизации обращений граждан. Ваша задача — внимательно проанализировать текст жалобы и точно определить:
1.  Ответственное ведомство (департамент, министерство, служба), которое должно заняться решением изложенной проблемы.
2.  Тип жалобы: "личная" или "общегражданская".

Жалоба:
"{item.text}"

Критерии для определения типа жалобы:
*   **Личная:** Жалоба касается проблемы, затрагивающей непосредственно одного человека или его семью, и требует индивидуального рассмотрения или предоставления персональной услуги (например, невыплата зарплаты, проблемы с оформлением личных документов, отказ в медицинской помощи конкретному лицу, проблемы с пенсией).
*   **Общегражданская:** Жалоба касается проблемы, затрагивающей неопределенный круг лиц, общественные блага, инфраструктуру, системные нарушения или общественный порядок (например, ямы на дорогах, отсутствие уличного освещения, свалки мусора, коррупция в учреждении, нелегальные стройки, проблемы с отоплением в районе).

**Для определения ответственного ведомства, руководствуйтесь следующими примерами распределения ответственности (основанными на типовых обращениях):**
... (rest of your detailed prompt examples) ...
Предоставьте ответ в следующем формате JSON (и только JSON, без дополнительных пояснений до или после):
{{
  "responsible_department": "НАЗВАНИЕ_ВЕДОМСТВА",
  "complaint_type": "личная" | "общегражданская",
  "adress": "если есть в тексте или null",
  "applicant_data": "если есть в тексте или null",
  "other":"любые релевантные данные которые есть в тексте которые могут помочь или null"
}}
"""
        try:
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }
            response = requests.post(OLLAMA_API_URL, json=payload, timeout=60)
            response.raise_for_status()
            llm_response_str = response.json().get("response", "")

            if not llm_response_str:
                llm_processing_error = "LLM returned an empty response string."
                current_status = IssueStatus.ANALYSIS_FAILED
            else:
                try:
                    parsed_llm_json = json.loads(llm_response_str)
                    llm_analysis_results.responsible_department = parsed_llm_json.get("responsible_department")
                    llm_analysis_results.complaint_type = parsed_llm_json.get("complaint_type")
                    llm_analysis_results.adress = parsed_llm_json.get("adress")
                    llm_analysis_results.applicant_data = parsed_llm_json.get("applicant_data")
                    llm_analysis_results.other = parsed_llm_json.get("other")
                    current_status = IssueStatus.ANALYZED if llm_analysis_results.responsible_department else IssueStatus.ANALYSIS_FAILED
                except json.JSONDecodeError as jde:
                    llm_processing_error = f"Failed to decode JSON from LLM: {str(jde)}. Raw response: '{llm_response_str[:200]}...'"
                    current_status = IssueStatus.ANALYSIS_FAILED
                except (TypeError, AttributeError) as e:
                    llm_processing_error = f"LLM response was not in expected format for JSON parsing: {str(e)}. Type: {type(llm_response_str)}"
                    current_status = IssueStatus.ANALYSIS_FAILED
        except requests.exceptions.RequestException as req_err:
            llm_processing_error = f"Ollama API request error: {str(req_err)}"
            current_status = IssueStatus.ANALYSIS_FAILED
        except Exception as e:
            llm_processing_error = f"An unexpected error occurred during LLM processing: {str(e)}"
            current_status = IssueStatus.ANALYSIS_FAILED
    else:
        current_status = IssueStatus.NEW


    db_record = models.ComplaintAnalysis(
        original_complaint=item.text,
        submission_type_by_user=item.submission_type_by_user,
        source=item.source,
        source_user_id=item.source_user_id,
        source_username=item.source_username,
        user_first_name=item.user_first_name,
        responsible_department=llm_analysis_results.responsible_department,
        complaint_type=llm_analysis_results.complaint_type,
        address=llm_analysis_results.adress,
        applicant_data=llm_analysis_results.applicant_data,
        other_details=llm_analysis_results.other,
        llm_processing_error=llm_processing_error,
        status=current_status
    )

    try:
        db.add(db_record)
        db.commit()
        db.refresh(db_record)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail={"message": f"Could not save data to database: {str(e)}"})

    return SubmissionResponse(
        saved_record_id=db_record.id,
        original_text=db_record.original_complaint,
        submission_type_by_user=db_record.submission_type_by_user,
        source=db_record.source,
        source_user_id=db_record.source_user_id,
        status=db_record.status,
        analysis=llm_analysis_results if item.submission_type_by_user == UserSubmissionType.COMPLAINT and not llm_processing_error else None,
        llm_processing_error=llm_processing_error,
        message="Submission processed successfully."
    )



@app.get("/issues/", response_model=List[IssueDetails])
def get_issues_for_user(
    source: SubmissionSource,
    source_user_id: str,
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 20
):
    issues = db.query(models.ComplaintAnalysis)\
               .filter(models.ComplaintAnalysis.source == source,
                       models.ComplaintAnalysis.source_user_id == source_user_id)\
               .order_by(models.ComplaintAnalysis.created_at.desc())\
               .offset(skip)\
               .limit(limit)\
               .all()
    if not issues:
        return []
    return issues