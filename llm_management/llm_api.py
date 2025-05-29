from fastapi import FastAPI, HTTPException, Depends ,Query
from pydantic import BaseModel, Field
from typing import Optional, List
import requests
import json
import os
import sys
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from datetime import datetime
from sqlalchemy import desc, extract
from collections import Counter
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta
import models
from models import SubmissionSource, UserSubmissionType, IssueStatus, SeverityLevel, ComplaintAnalysis
from database import engine, get_db
from sqlalchemy import func, or_
from auth.core import deps as auth_deps
from auth.db import models as auth_models
load_dotenv()
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:27b")

models.Base.metadata.create_all(bind=engine)

app = FastAPI(root_path="/api")

class StatsByCategoryItem(BaseModel):
    category: Optional[str]
    count: int

class StatsByStatusItem(BaseModel):
    status: IssueStatus
    count: int

class StatsByDepartmentItem(BaseModel):
    department: Optional[str]
    count: int

class StatsBySeverityItem(BaseModel):
    severity: Optional[SeverityLevel]
    count: int

class TimeSeriesDataPoint(BaseModel):
    period: str
    count: int

class OverallStatsResponse(BaseModel):
    total_issues: int
    by_category: List[StatsByCategoryItem]
    by_status: List[StatsByStatusItem]
    by_responsible_department: List[StatsByDepartmentItem]
    by_severity: List[StatsBySeverityItem]


class IssueSubmissionItem(BaseModel):
    text: str = Field(..., min_length=1, description="Основной текст жалобы или обращения.")
    submission_type_by_user: UserSubmissionType = Field(...,
                                                        description="Тип обращения, указанный пользователем ('жалоба' или 'просьба').")
    source: SubmissionSource = Field(..., description="Источник обращения (например, 'telegram').")
    source_user_id: str = Field(..., description="ID пользователя из источника (например, Telegram user ID).")
    source_username: Optional[str] = None
    user_first_name: Optional[str] = None


class LLMAnalysisResult(BaseModel):
    responsible_department: Optional[str] = None
    complaint_type: Optional[str] = None
    complaint_category: Optional[str] = None
    complaint_subcategory: Optional[str] = None
    address_text: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    district: Optional[str] = None
    severity_level: Optional[SeverityLevel] = None
    applicant_data: Optional[str] = None
    other_details: Optional[str] = None


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
    original_complaint_text: str
    submission_type_by_user: Optional[UserSubmissionType]
    source: SubmissionSource
    source_user_id: str
    source_username: Optional[str]
    user_first_name: Optional[str]

    responsible_department: Optional[str]
    complaint_type: Optional[str]
    complaint_category: Optional[str]
    complaint_subcategory: Optional[str]
    address_text: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    district: Optional[str]
    severity_level: Optional[SeverityLevel]
    applicant_data: Optional[str]
    other_details: Optional[str]

    status: IssueStatus
    llm_processing_error: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    resolved_at: Optional[datetime]
    resolution_details: Optional[str]
    user_feedback_on_resolution: Optional[str]

    class Config:
        orm_mode = True
        use_enum_values = True

@app.post("/submit-issue/", response_model=SubmissionResponse, status_code=201)
def submit_issue(item: IssueSubmissionItem, db: Session = Depends(get_db)):
    llm_analysis_results = LLMAnalysisResult()
    llm_processing_error = None
    current_status = IssueStatus.NEW  # Статус по умолчанию

    if item.submission_type_by_user == UserSubmissionType.COMPLAINT:
        current_status = IssueStatus.PENDING_ANALYSIS
        prompt = f"""
        Вы — высококвалифицированный AI-аналитик в центре обработки обращений граждан. Ваша задача — точно проанализировать текст жалобы и извлечь структурированную информацию.

        Текст жалобы:
        "{item.text}"

        Проанализируйте жалобу и предоставьте ответ ИСКЛЮЧИТЕЛЬНО в формате JSON со следующими полями:

        {{
          "responsible_department": "НАЗВАНИЕ_ВЕДОМСТВА (например, 'Мэрия города Бишкек, Департамент ЖКХ', 'МВД КР, ГУВД г. Бишкек', 'Министерство здравоохранения КР', или null)",
          "complaint_type": "личная" | "общегражданская" | null,
          "complaint_category": "ОДНА ИЗ КАТЕГОРИЙ НИЖЕ" | "Другое" | null,
          "complaint_subcategory": "КРАТКОЕ ОПИСАНИЕ ПРОБЛЕМЫ (например, 'вывоз мусора', 'ямы на ул. Киевская', 'грубость врача в поликлинике №5', или null)",
          "address_text": "СТРОКА (полный адрес, как он указан в тексте, включая город, улицу, дом, квартиру, если есть; или null, если адрес не указан или не относится к проблеме)",
          "latitude": ЧИСЛО (широта, если можно однозначно определить, иначе null),
          "longitude": ЧИСЛО (долгота, если можно однозначно определить, иначе null),
          "district": "СТРОКА (название района города или области, если указано или очевидно из адреса; или null)",
          "severity_level": "низкий" | "средний" | "высокий" | "критический" | null,
          "applicant_data": "СТРОКА (ФИО, телефон, email заявителя, если указаны в тексте; или null)",
          "other_details": "СТРОКА (любые другие важные детали, не вошедшие в другие поля, например, конкретные даты, номера документов, описание последствий; или null)"
        }}

        Основные категории для поля "complaint_category":
        *   "Городская инфраструктура и ЖКХ" (мусор, дороги, свет, вода, отопление, стройки)
        *   "Общественный порядок и безопасность" (шум, драки, преступления, пожары)
        *   "Образование и дети" (школы, детсады, поборы, питание)
        *   "Здравоохранение" (отказ в помощи, грубость врачей, лекарства, очереди)
        *   "Коррупция и госуслуги" (вымогательство, проблемы с документами, очереди в госорганах)
        *   "Экология и животные" (свалки, вырубка деревьев, загрязнение, бродячие животные)
        *   "Интернет, цифровые услуги и связь" (проблемы с доступом к госуслугам онлайн, интернет от госпровайдера)
        *   "Работа и социальная защита" (невыплата зарплаты, пенсии, пособия, условия труда)
        *   "Экономика и бизнес" (барьеры для бизнеса, тарифы, налоги)
        *   "Другое" (если ни одна категория не подходит)

        Критерии для полей:

        1.  **responsible_department**: Укажите наиболее вероятное ответственное ведомство, основываясь на категории и сути проблемы. Примеры: 'Мэрия г. Бишкек', 'Тазалык', 'МВД КР', 'Министерство образования и науки КР', 'Министерство здравоохранения КР', 'Министерство цифрового развития КР'. Если неясно, укажите null.

        2.  **complaint_type**:
            *   'личная': Проблема затрагивает одного человека/семью.
            *   'общегражданская': Проблема затрагивает неопределенный круг лиц, общественные блага.
            Если неясно, укажите null.

        3.  **complaint_category**: Выберите ОДНУ наиболее подходящую категорию из списка выше.
        4.  **complaint_subcategory**: Кратко опишите суть проблемы в 2-5 словах (например, 'отсутствие горячей воды', 'незаконная парковка во дворе', 'поборы в школе №10').

        5.  **address_text**: Точно извлеките адрес, связанный с проблемой.

        6.  **latitude**, **longitude**: Только если явно указаны или легко определяются. Не пытайтесь геокодировать. Иначе null.

        7.  **district**: Район города/области, если указан или очевиден. Иначе null.

        8.  **severity_level**: Оцените серьезность:
            *   'низкий': Незначительное неудобство.
            *   'средний': Существенное неудобство.
            *   'высокий': Серьезная проблема, влияет на качество жизни/здоровье.
            *   'критический': ЧС, угроза жизни/здоровью многих.
            Если неясно, укажите null.

        9.  **applicant_data**: Только если явно указаны контактные данные или ФИО.

        10. **other_details**: Все, что важно, но не вошло в другие поля.

        Строго следуйте формату JSON. Не добавляйте никаких пояснений вне JSON.
"""
        try:
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json"
            }
            response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)  # Увеличено время ожидания
            response.raise_for_status()

            llm_response_str = response.json().get("response", "")

            if not llm_response_str:
                llm_processing_error = "LLM вернул пустой ответ."
                current_status = IssueStatus.ANALYSIS_FAILED
            else:
                try:
                    if llm_response_str.strip().startswith("```json"):
                        llm_response_str = llm_response_str.strip()[7:]
                        if llm_response_str.strip().endswith("```"):
                            llm_response_str = llm_response_str.strip()[:-3]

                    parsed_llm_json = json.loads(llm_response_str.strip())

                    llm_analysis_results = LLMAnalysisResult(**parsed_llm_json)
                    current_status = IssueStatus.ANALYZED if llm_analysis_results.responsible_department else IssueStatus.ANALYSIS_FAILED

                except json.JSONDecodeError as jde:
                    llm_processing_error = f"Ошибка декодирования JSON от LLM: {str(jde)}. Ответ LLM (начало): '{llm_response_str[:300]}...'"
                    current_status = IssueStatus.ANALYSIS_FAILED
                except Exception as e:
                    llm_processing_error = f"Ошибка обработки ответа LLM или валидации данных: {str(e)}. Ответ LLM (начало): '{llm_response_str[:300]}...'"
                    current_status = IssueStatus.ANALYSIS_FAILED

        except requests.exceptions.Timeout:
            llm_processing_error = f"Тайм-аут запроса к Ollama API ({OLLAMA_API_URL})."
            current_status = IssueStatus.ANALYSIS_FAILED
        except requests.exceptions.RequestException as req_err:
            llm_processing_error = f"Ошибка запроса к Ollama API: {str(req_err)}"
            current_status = IssueStatus.ANALYSIS_FAILED
        except Exception as e:
            llm_processing_error = f"Непредвиденная ошибка при обработке LLM: {str(e)}"
            current_status = IssueStatus.ANALYSIS_FAILED

    elif item.submission_type_by_user == UserSubmissionType.REQUEST:
        current_status = IssueStatus.NEW

    db_record = ComplaintAnalysis(
        original_complaint_text=item.text,
        submission_type_by_user=item.submission_type_by_user,
        source=item.source,
        source_user_id=item.source_user_id,
        source_username=item.source_username,
        user_first_name=item.user_first_name,

        responsible_department=llm_analysis_results.responsible_department,
        complaint_type=llm_analysis_results.complaint_type,
        complaint_category=llm_analysis_results.complaint_category,
        complaint_subcategory=llm_analysis_results.complaint_subcategory,
        address_text=llm_analysis_results.address_text,
        latitude=llm_analysis_results.latitude,
        longitude=llm_analysis_results.longitude,
        district=llm_analysis_results.district,
        severity_level=llm_analysis_results.severity_level,
        applicant_data=llm_analysis_results.applicant_data,
        other_details=llm_analysis_results.other_details,

        llm_processing_error=llm_processing_error,
        status=current_status
    )

    try:
        db.add(db_record)
        db.commit()
        db.refresh(db_record)
    except Exception as e:
        db.rollback()
        print(f"Database save error: {str(e)}")
        raise HTTPException(status_code=500, detail={"message": f"Не удалось сохранить данные в базу: {str(e)}"})

    return SubmissionResponse(
        saved_record_id=db_record.id,
        original_text=db_record.original_complaint_text,
        submission_type_by_user=db_record.submission_type_by_user,
        source=db_record.source,
        source_user_id=db_record.source_user_id,
        status=db_record.status,
        analysis=llm_analysis_results if current_status == IssueStatus.ANALYZED else None,
        llm_processing_error=llm_processing_error,
        message="Обращение успешно обработано и сохранено."
    )


class IssueListParams(BaseModel):
    skip: int = Query(0, ge=0)
    limit: int = Query(20, ge=1, le=100)
    sort_by: str = Query("created_at", description="Поле для сортировки (id, created_at, status, etc.)")
    order: str = Query("desc", description="Порядок сортировки (asc или desc)")


@app.get("/all_issues/", response_model=List[IssueDetails],
         summary="Получить список всех обращений (для работников/админов)")
def get_all_issues(
        params: IssueListParams = Depends(),
        db: Session = Depends(get_db),
        current_user: auth_models.User = Depends(auth_deps.get_current_active_user)  # Защита эндпоинта
):

    query = db.query(ComplaintAnalysis)

    sort_column_name = params.sort_by
    if not hasattr(ComplaintAnalysis, sort_column_name):
        sort_column_name = "created_at"

    sort_column = getattr(ComplaintAnalysis, sort_column_name)

    if params.order.lower() == "desc":
        query = query.order_by(desc(sort_column))
    else:
        query = query.order_by(sort_column)

    issues = query.offset(params.skip).limit(params.limit).all()
    return issues

@app.get("/issues/", response_model=List[IssueDetails])
def get_issues_for_user(
        source_user_id: str,
        db: Session = Depends(get_db),
        source: Optional[SubmissionSource] = None,
        skip: int = 0,
        limit: int = 20
):
    search_term_lower = source_user_id.lower()

    query = db.query(ComplaintAnalysis).filter(
        or_(
            func.lower(ComplaintAnalysis.source_user_id) == search_term_lower,
            func.lower(ComplaintAnalysis.source_username) == search_term_lower
        )
    )

    if source:
        query = query.filter(ComplaintAnalysis.source == source)

    issues = query.order_by(ComplaintAnalysis.created_at.desc()) \
        .offset(skip) \
        .limit(limit) \
        .all()

    return issues


@app.get("/issue/{issue_id}", response_model=IssueDetails)
def get_issue_details(issue_id: int, db: Session = Depends(get_db),current_user: auth_models.User = Depends(auth_deps.get_current_active_user)):
    issue = db.query(ComplaintAnalysis).filter(ComplaintAnalysis.id == issue_id).first()
    if issue is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    return issue


class IssueUpdateRequest(BaseModel):
    status: Optional[IssueStatus] = None
    responsible_department: Optional[str] = None
    complaint_category: Optional[str] = None
    complaint_subcategory: Optional[str] = None
    address_text: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    district: Optional[str] = None
    severity_level: Optional[SeverityLevel] = None


class ResolutionRequest(BaseModel):
    resolution_details: str = Field(..., min_length=10,
                                    description="Подробное описание принятых мер по решению проблемы.")
    resolved_at: Optional[datetime] = Field(default_factory=datetime.utcnow,
                                            description="Дата и время решения проблемы. По умолчанию текущее время UTC.")


class UserFeedbackRequest(BaseModel):
    user_feedback_on_resolution: str = Field(..., min_length=1,
                                             description="Отзыв пользователя о качестве решения проблемы (текст или оценка).")


@app.patch("/issue/{issue_id}", response_model=IssueDetails, summary="Обновить детали обращения")
def update_issue_details(
        issue_id: int,
        update_data: IssueUpdateRequest,
        db: Session = Depends(get_db),
        current_user: auth_models.User = Depends(auth_deps.get_current_active_user)
):
    issue = db.query(ComplaintAnalysis).filter(ComplaintAnalysis.id == issue_id).first()
    if issue is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено")

    update_data_dict = update_data.dict(exclude_unset=True)

    for key, value in update_data_dict.items():
        setattr(issue, key, value)

    issue.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(issue)
    except Exception as e:
        db.rollback()
        print(f"Ошибка обновления обращения {issue_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Не удалось обновить обращение: {str(e)}")

    return issue


@app.post("/issue/{issue_id}/resolve", response_model=IssueDetails, summary="Отметить обращение как решенное")
def mark_issue_as_resolved(
        issue_id: int,
        resolution_data: ResolutionRequest,
        db: Session = Depends(get_db),
        current_user: auth_models.User = Depends(auth_deps.get_current_active_user)
):
    issue = db.query(ComplaintAnalysis).filter(ComplaintAnalysis.id == issue_id).first()
    if issue is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено")

    if issue.status == IssueStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Обращение уже отмечено как решенное.")

    issue.status = IssueStatus.RESOLVED
    issue.resolution_details = resolution_data.resolution_details
    issue.resolved_at = resolution_data.resolved_at if resolution_data.resolved_at else datetime.utcnow()
    issue.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(issue)
    except Exception as e:
        db.rollback()
        print(f"Ошибка при отметке обращения {issue_id} как решенного: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Не удалось обновить обращение: {str(e)}")

    return issue


@app.post("/issue/{issue_id}/feedback", response_model=IssueDetails, summary="Добавить отзыв пользователя о решении")
def add_user_feedback_to_issue(
        issue_id: int,
        feedback_data: UserFeedbackRequest,
        db: Session = Depends(get_db)
):
    issue = db.query(ComplaintAnalysis).filter(ComplaintAnalysis.id == issue_id).first()
    if issue is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено")


    if issue.status != IssueStatus.RESOLVED and issue.status != IssueStatus.PENDING_USER_FEEDBACK:
        raise HTTPException(status_code=400, detail="Отзыв можно оставить только по решенному обращению или ожидающему отзыв.")

    issue.user_feedback_on_resolution = feedback_data.user_feedback_on_resolution
    issue.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(issue)
    except Exception as e:
        db.rollback()
        print(f"Ошибка при добавлении отзыва к обращению {issue_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Не удалось обновить обращение: {str(e)}")

    return issue


@app.get("/stats/overall", response_model=OverallStatsResponse, summary="Получить общую статистику по обращениям")
def get_overall_stats(
        db: Session = Depends(get_db),
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        source: Optional[SubmissionSource] = None,
        current_user: auth_models.User = Depends(auth_deps.get_current_active_user)
):
    query_base = db.query(ComplaintAnalysis)

    if date_from:
        query_base = query_base.filter(ComplaintAnalysis.created_at >= date_from)
    if date_to:
        query_base = query_base.filter(ComplaintAnalysis.created_at < date_to + timedelta(
            days=1) if date_to else ComplaintAnalysis.created_at <= datetime.utcnow())
    if source:
        query_base = query_base.filter(ComplaintAnalysis.source == source)

    total_issues = query_base.count()

    stats_category_query = query_base.with_entities(
        ComplaintAnalysis.complaint_category,
        func.count(ComplaintAnalysis.id).label("count")
    ).group_by(ComplaintAnalysis.complaint_category).order_by(desc("count")).all()

    by_category = [StatsByCategoryItem(category=row.complaint_category if row.complaint_category else "Не указана",
                                       count=row.count) for row in stats_category_query]

    stats_status_query = query_base.with_entities(
        ComplaintAnalysis.status,
        func.count(ComplaintAnalysis.id).label("count")
    ).group_by(ComplaintAnalysis.status).order_by(desc("count")).all()

    by_status = [StatsByStatusItem(status=row.status, count=row.count) for row in stats_status_query]

    stats_department_query = query_base.with_entities(
        ComplaintAnalysis.responsible_department,
        func.count(ComplaintAnalysis.id).label("count")
    ).group_by(ComplaintAnalysis.responsible_department).order_by(desc("count")).all()

    by_responsible_department = [
        StatsByDepartmentItem(department=row.responsible_department if row.responsible_department else "Не назначен",
                              count=row.count) for row in stats_department_query]

    stats_severity_query = query_base.with_entities(
        ComplaintAnalysis.severity_level,
        func.count(ComplaintAnalysis.id).label("count")
    ).group_by(ComplaintAnalysis.severity_level).order_by(desc("count")).all()
    by_severity = [
        StatsBySeverityItem(severity=row.severity_level, count=row.count) for row
        in stats_severity_query]
    return OverallStatsResponse(
        total_issues=total_issues,
        by_category=by_category,
        by_status=by_status,
        by_responsible_department=by_responsible_department,
        by_severity=by_severity
    )


@app.get("/stats/timeline", response_model=List[TimeSeriesDataPoint],
         summary="Получить статистику по времени (динамика)")
def get_timeline_stats(
        db: Session = Depends(get_db),
        group_by_period: str = Query("day", enum=["day", "month", "year"],
                                     description="Группировать по дню, месяцу или году"),
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        category: Optional[str] = None,
        department: Optional[str] = None,
        status: Optional[IssueStatus] = None,
        severity: Optional[SeverityLevel] = None,
        current_user: auth_models.User = Depends(auth_deps.get_current_active_user)
):
    query_base = db.query(ComplaintAnalysis)
    if date_from:
        query_base = query_base.filter(ComplaintAnalysis.created_at >= date_from)
    if date_to:
        query_base = query_base.filter(ComplaintAnalysis.created_at < date_to + timedelta(
            days=1) if date_to else ComplaintAnalysis.created_at <= datetime.utcnow())
    if category:
        query_base = query_base.filter(ComplaintAnalysis.complaint_category == category)
    if department:
        query_base = query_base.filter(ComplaintAnalysis.responsible_department == department)
    if status:
        query_base = query_base.filter(ComplaintAnalysis.status == status)
    if severity:
        query_base = query_base.filter(ComplaintAnalysis.severity_level == severity)

    if group_by_period == "day":
        period_func = func.date_trunc('day', ComplaintAnalysis.created_at)
        date_format_str = "%Y-%m-%d"
    elif group_by_period == "month":
        period_func = func.date_trunc('month', ComplaintAnalysis.created_at)
        date_format_str = "%Y-%m"
    elif group_by_period == "year":
        period_func = func.date_trunc('year', ComplaintAnalysis.created_at)
        date_format_str = "%Y"
    else:
        period_func = func.date_trunc('day', ComplaintAnalysis.created_at)
        date_format_str = "%Y-%m-%d"

    timeline_query = query_base.with_entities(
        period_func.label("period_start"),
        func.count(ComplaintAnalysis.id).label("count")
    ).group_by("period_start").order_by("period_start").all()

    result = []
    for row in timeline_query:
        period_str = row.period_start.strftime(date_format_str) if isinstance(row.period_start, datetime) else str(
            row.period_start)
        result.append(TimeSeriesDataPoint(period=period_str, count=row.count))

    return result


@app.get("/stats/top_problematic_addresses", response_model=List[dict], summary="Топ проблемных адресов")
def get_top_problematic_addresses(
        limit: int = Query(1, ge=1, le=100),
        db: Session = Depends(get_db),
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        category: Optional[str] = None,
        district: Optional[str] = None,
        current_user: auth_models.User = Depends(auth_deps.get_current_active_user)
):
    query_base = db.query(
        ComplaintAnalysis.address_text,
        func.count(ComplaintAnalysis.id).label("complaint_count")
    ).filter(ComplaintAnalysis.address_text != None)

    if date_from:
        query_base = query_base.filter(ComplaintAnalysis.created_at >= date_from)
    if date_to:
        query_base = query_base.filter(ComplaintAnalysis.created_at < date_to + timedelta(
            days=1) if date_to else ComplaintAnalysis.created_at <= datetime.utcnow())
    if category:
        query_base = query_base.filter(ComplaintAnalysis.complaint_category == category)
    if district:
        query_base = query_base.filter(ComplaintAnalysis.district == district)

    top_addresses = query_base.group_by(ComplaintAnalysis.address_text) \
        .order_by(desc("complaint_count")) \
        .limit(limit) \
        .all()

    return [{"address": row.address_text, "complaint_count": row.complaint_count} for row in top_addresses]


