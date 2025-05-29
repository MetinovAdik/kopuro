import logging
import os
from datetime import datetime

import httpx
import json
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CENTRAL_API_URL = os.getenv("CENTRAL_API_URL", "http://localhost:8000/submit-issue/")
CENTRAL_API_GET_ISSUES_URL = os.getenv("CENTRAL_API_GET_ISSUES_URL",
                                       "http://localhost:8000/issues/")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

CHOOSE_ACTION, GET_COMPLAINT = range(2)

SUBMISSION_TYPE_KEY = "submission_type"
COMPLAINT_KEYWORD_RU = "жалоба"




async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    await update.message.reply_html(
        rf"Привет, {user.mention_html()}! Я бот для сбора жалоб."
        f"\n\nЧтобы подать жалобу, напишите: <b>{COMPLAINT_KEYWORD_RU}</b>"
        f"\n\nВы также можете использовать команду /cancel для отмены в любой момент "
        f"или /my_submissions для просмотра ваших заявок."
    )
    return CHOOSE_ACTION


async def choose_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.lower().strip()
    context.user_data[SUBMISSION_TYPE_KEY] = None

    if text == COMPLAINT_KEYWORD_RU:
        context.user_data[SUBMISSION_TYPE_KEY] = COMPLAINT_KEYWORD_RU
        await update.message.reply_text(
            "Пожалуйста, опишите вашу жалобу:",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_COMPLAINT
    else:
        await update.message.reply_text(
            f"Пожалуйста, введите '{COMPLAINT_KEYWORD_RU}', "
            f"или используйте /cancel для отмены."
        )
        return CHOOSE_ACTION


async def process_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_text = update.message.text
    user = update.effective_user
    submission_type_by_user = context.user_data.get(SUBMISSION_TYPE_KEY)  # Will be "жалоба"

    if not submission_type_by_user:
        await update.message.reply_text(
            "Произошла ошибка определения типа заявки. Пожалуйста, начните сначала командой /start.")
        context.user_data.pop(SUBMISSION_TYPE_KEY, None)
        return ConversationHandler.END

    payload = {
        "text": user_text,
        "submission_type_by_user": submission_type_by_user,  # This will be "жалоба"
        "source": "telegram",
        "source_user_id": str(user.id),
        "source_username": user.username,
        "user_first_name": user.first_name
    }

    api_response_message = ""
    saved_record_id = None

    async with httpx.AsyncClient(timeout=70.0) as client:
        try:
            logger.info(f"Sending to API: {CENTRAL_API_URL} with payload: {payload}")
            response = await client.post(CENTRAL_API_URL, json=payload)
            response.raise_for_status()

            api_data = response.json()
            logger.info(f"API Response for user {user.id}: {api_data}")

            saved_record_id = api_data.get("saved_record_id")
            api_status = api_data.get("status", "unknown")
            llm_error = api_data.get("llm_processing_error")
            analysis_results = api_data.get("analysis")

            api_response_message = f"Спасибо! Ваша {COMPLAINT_KEYWORD_RU} принята (ID: #{saved_record_id}, Статус: {api_status})."

            if llm_error:
                api_response_message += f"\n\n⚠️ Не удалось полностью автоматически проанализировать жалобу. Причина: {llm_error[:200]}"
            elif analysis_results and analysis_results.get("responsible_department"):
                dept = analysis_results.get("responsible_department")
                comp_type = analysis_results.get("complaint_type", "не определен")  # e.g. личная / общегражданская
                api_response_message += f"\n\nАнализ: Ведомство - {dept}, Тип - {comp_type}."
            elif api_status == "analysis_failed" and not llm_error:
                api_response_message += "\n\nАнализ: Не удалось определить ответственное ведомство по тексту."
            elif api_status != "analyzed":
                api_response_message += "\nЖалоба принята, но автоматический анализ не был успешно завершен."


        except httpx.HTTPStatusError as e:
            error_detail = "Неизвестная ошибка API."
            try:
                error_content = e.response.json()
                error_detail = error_content.get("detail", {}).get("message", e.response.text[:200]) \
                    if isinstance(error_content.get("detail"), dict) \
                    else error_content.get("detail", e.response.text[:200])
            except json.JSONDecodeError:
                error_detail = e.response.text[:200]
            logger.error(f"HTTPStatusError calling API for user {user.id}: {e.response.status_code} - {error_detail}",
                         exc_info=True)
            api_response_message = f"Ошибка при отправке данных в систему ({e.response.status_code}): {error_detail}"
        except httpx.RequestError as e:
            logger.error(f"RequestError calling API for user {user.id}: {str(e)}", exc_info=True)
            api_response_message = f"Ошибка подключения к системе обработки заявок: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error processing submission for user {user.id}: {e}", exc_info=True)
            api_response_message = "Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."

    await update.message.reply_text(api_response_message)

    context.user_data.pop(SUBMISSION_TYPE_KEY, None)
    if saved_record_id:
        await update.message.reply_html(
            f"Хотите подать еще одну жалобу? \n"
            f"Напишите: <b>{COMPLAINT_KEYWORD_RU}</b>.\n"
            f"Или используйте /cancel для завершения, или /my_submissions для просмотра ваших заявок."
        )
        return CHOOSE_ACTION
    else:
        await update.message.reply_text("Если проблема сохранится, обратитесь в поддержку. Начать заново: /start")
        return ConversationHandler.END


async def my_submissions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    params = {
        "source": "telegram",
        "source_user_id": str(user.id)
    }

    async with httpx.AsyncClient() as client:
        try:
            logger.info(
                f"Fetching submissions for user {user.id} from {CENTRAL_API_GET_ISSUES_URL} with params {params}")
            response = await client.get(CENTRAL_API_GET_ISSUES_URL, params=params)
            response.raise_for_status()
            submissions_list = response.json()

            if not submissions_list:
                await update.message.reply_text("У вас пока нет зарегистрированных жалоб.")
                return

            response_parts = []
            current_message = "Ваши заявки:\n\n"
            MAX_MESSAGE_LENGTH = 4096

            for sub_data in submissions_list:
                text_preview = (sub_data['original_complaint_text'][:75] + '...') if len(
                    sub_data['original_complaint_text']) > 75 else sub_data['original_complaint_text']

                entry = (
                    f"<b>ID:</b> {sub_data['id']}\n"
                    f"<b>Тип:</b> {sub_data.get('submission_type_by_user', 'жалоба')}\n"
                    f"<b>Статус:</b> {sub_data['status']}\n"
                    f"<b>Текст:</b> {text_preview}\n"
                )

                if sub_data.get('responsible_department'):
                    entry += f"<b>Отв. ведомство (анализ):</b> {sub_data['responsible_department']}\n"
                if sub_data.get('complaint_type'):
                    entry += f"<b>Тип (анализ):</b> {sub_data['complaint_type']}\n"
                if sub_data.get('complaint_category'):
                    entry += f"<b>Категория (анализ):</b> {sub_data['complaint_category']}\n"
                if sub_data.get('address_text'):
                    entry += f"<b>Адрес (анализ):</b> {sub_data['address_text'][:50]}...\n"
                if sub_data.get('severity_level'):
                    entry += f"<b>Серьезность (анализ):</b> {sub_data['severity_level']}\n"
                if sub_data.get('llm_processing_error'):
                    entry += f"<b>Ошибка анализа:</b> {sub_data['llm_processing_error'][:70]}...\n"

                created_at_str = 'N/A'
                if sub_data.get('created_at'):
                    try:
                        dt_obj = datetime.fromisoformat(sub_data['created_at'].replace('Z', '+00:00'))
                        created_at_str = dt_obj.strftime('%Y-%m-%d %H:%M')
                    except ValueError:
                        created_at_str = sub_data['created_at']

                entry += f"<b>Дата:</b> {created_at_str}\n\n"

                if len(current_message) + len(entry) > MAX_MESSAGE_LENGTH:
                    response_parts.append(current_message)
                    current_message = ""
                current_message += entry

            if current_message and current_message.strip() != "Ваши заявки:\n\n":
                response_parts.append(current_message)

            if not response_parts:
                await update.message.reply_text("Не удалось сформировать список ваших заявок.")
                return

            for part in response_parts:
                await update.message.reply_html(part)

            logger.info(f"User {user.id} viewed their submissions. Count: {len(submissions_list)}")

        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTPStatusError fetching submissions for user {user.id}: {e.response.status_code} - {e.response.text[:200]}",
                exc_info=True)
            await update.message.reply_text("Произошла ошибка при загрузке ваших заявок (сервер вернул ошибку).")
        except httpx.RequestError as e:
            logger.error(f"RequestError fetching submissions for user {user.id}: {str(e)}", exc_info=True)
            await update.message.reply_text("Произошла ошибка подключения при загрузке ваших заявок.")
        except Exception as e:
            logger.error(f"Unexpected error fetching submissions for user {user.id}: {e}", exc_info=True)
            await update.message.reply_text("Произошла непредвиденная ошибка при загрузке ваших заявок.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    logger.info("User %s (%s) canceled the conversation.", user.first_name, user.id)
    await update.message.reply_text(
        "Действие отменено. Если хотите начать заново, введите /start.",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.pop(SUBMISSION_TYPE_KEY, None)
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "Я бот для сбора ваших жалоб. Все данные централизованно обрабатываются нашей системой.\n\n"
        "<b>Основные команды:</b>\n"
        "/start - начать процесс подачи жалобы.\n"
        "/my_submissions - посмотреть список ваших предыдущих заявок и их статусы.\n"
        "/cancel - отменить текущее действие (например, если вы передумали писать жалобу).\n"
        "/help - показать это сообщение.\n\n"
        "<b>Как подать заявку:</b>\n"
        "1. Введите /start.\n"
        f"2. Напишите '{COMPLAINT_KEYWORD_RU}' для жалобы.\n"
        "3. Следуйте инструкциям бота и опишите вашу ситуацию.\n"
        "Ваша жалоба будет автоматически проанализирована для определения ответственного ведомства.\n"
        "После отправки заявка будет зарегистрирована в центральной системе."
    )
    await update.message.reply_html(help_text)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Токен TELEGRAM_BOT_TOKEN не найден в .env файле")
        return
    if not CENTRAL_API_URL:
        logger.error("CENTRAL_API_URL не найден в .env файле. Бот не сможет отправлять данные.")
        return
    if not CENTRAL_API_GET_ISSUES_URL:
        logger.error("CENTRAL_API_GET_ISSUES_URL не найден в .env файле. Бот не сможет получать список заявок.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    keywords_regex = f"^({COMPLAINT_KEYWORD_RU})$"

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(keywords_regex), choose_action),
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_action)
            ],
            GET_COMPLAINT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_submission)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("my_submissions", my_submissions_command))

    logger.info("Телеграм бот (клиент API) запускается...")
    application.run_polling()


if __name__ == "__main__":
    main()