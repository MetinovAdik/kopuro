import logging
import os
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from db_setup import get_async_db
from models import Submission, SubmissionType

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

CHOOSE_ACTION, GET_COMPLAINT, GET_REQUEST = range(3)
SUBMISSION_TYPE_KEY = "submission_type"
COMPLAINT_KEYWORD_RU = SubmissionType.COMPLAINT.value
REQUEST_KEYWORD_RU = SubmissionType.REQUEST.value

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    await update.message.reply_html(
        rf"Привет, {user.mention_html()}! Я бот для сбора жалоб и просьб."
        f"\n\nЧтобы подать жалобу, напишите: <b>{COMPLAINT_KEYWORD_RU}</b>"
        f"\nЧтобы оставить просьбу, напишите: <b>{REQUEST_KEYWORD_RU}</b>"
        f"\n\nВы также можете использовать команду /cancel для отмены в любой момент "
        f"или /my_submissions для просмотра ваших заявок."
    )
    return CHOOSE_ACTION

async def choose_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.lower().strip()
    context.user_data[SUBMISSION_TYPE_KEY] = None

    if text == COMPLAINT_KEYWORD_RU:
        context.user_data[SUBMISSION_TYPE_KEY] = SubmissionType.COMPLAINT
        await update.message.reply_text(
            "Пожалуйста, опишите вашу жалобу:",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_COMPLAINT
    elif text == REQUEST_KEYWORD_RU:
        context.user_data[SUBMISSION_TYPE_KEY] = SubmissionType.REQUEST
        await update.message.reply_text(
            "Пожалуйста, опишите вашу просьбу:",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_REQUEST
    else:
        await update.message.reply_text(
            f"Пожалуйста, введите '{COMPLAINT_KEYWORD_RU}' или '{REQUEST_KEYWORD_RU}', "
            f"или используйте /cancel для отмены."
        )
        return CHOOSE_ACTION

async def process_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_text = update.message.text
    user = update.effective_user
    submission_type_from_context = context.user_data.get(SUBMISSION_TYPE_KEY)

    if not submission_type_from_context:
        await update.message.reply_text("Произошла ошибка определения типа заявки. Пожалуйста, начните сначала командой /start.")
        context.user_data.pop(SUBMISSION_TYPE_KEY, None)
        return ConversationHandler.END

    db_gen = None
    db: AsyncSession | None = None

    try:
        db_gen = get_async_db()
        db = await db_gen.__anext__()

        new_submission = Submission(
            user_id=user.id,
            username=user.username if user.username else str(user.id),
            first_name=user.first_name,
            submission_type=submission_type_from_context,
            text=user_text,
            status="new"
        )
        db.add(new_submission)
        await db.commit()
        await db.refresh(new_submission)
        logger.info(f"Saved submission: {new_submission.id} from {user.id} ({user.username})")
        await update.message.reply_text(
            f"Спасибо! Ваша {submission_type_from_context.value} принята и зарегистрирована под номером #{new_submission.id}."
        )
    except Exception as e:
        if db:
            try:
                await db.rollback()
            except Exception as rb_exc:
                logger.error(f"Error during rollback: {rb_exc}", exc_info=True)
        logger.error(f"Error saving submission for user {user.id}: {e}", exc_info=True)
        await update.message.reply_text("К сожалению, произошла ошибка при сохранении. Попробуйте позже.")
        context.user_data.pop(SUBMISSION_TYPE_KEY, None)
        return ConversationHandler.END
    finally:
        if db_gen:
            try:
                await db_gen.aclose()
            except Exception as gen_close_exc:
                logger.error(f"Error closing db_gen in process_submission: {gen_close_exc}", exc_info=True)

    context.user_data.pop(SUBMISSION_TYPE_KEY, None)
    await update.message.reply_html(
        f"Хотите подать еще одну заявку? \n"
        f"Напишите: <b>{COMPLAINT_KEYWORD_RU}</b> или <b>{REQUEST_KEYWORD_RU}</b>.\n"
        f"Или используйте /cancel для завершения, или /my_submissions для просмотра ваших заявок."
    )
    return CHOOSE_ACTION

async def my_submissions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_gen = None
    db: AsyncSession | None = None

    try:
        db_gen = get_async_db()
        db = await db_gen.__anext__()

        stmt = (
            select(Submission)
            .where(Submission.user_id == user.id)
            .order_by(Submission.created_at.desc())
        )
        result = await db.execute(stmt)
        submissions_list = result.scalars().all()

        if not submissions_list:
            await update.message.reply_text("У вас пока нет зарегистрированных жалоб или просьб.")
            return

        response_message = "Ваши заявки:\n\n"
        for sub in submissions_list:
            text_preview = (sub.text[:75] + '...') if len(sub.text) > 75 else sub.text
            response_message += (
                f"<b>ID:</b> {sub.id}\n"
                f"<b>Тип:</b> {sub.submission_type.value}\n" # .value gives "жалоба" or "просьба"
                f"<b>Статус:</b> {sub.status}\n"
                f"<b>Текст:</b> {text_preview}\n"
                f"<b>Дата:</b> {sub.created_at.strftime('%Y-%m-%d %H:%M') if sub.created_at else 'N/A'}\n\n"
            )

        MAX_MESSAGE_LENGTH = 4096
        if len(response_message) > MAX_MESSAGE_LENGTH:
            await update.message.reply_html("Ваш список заявок слишком длинный. Вот его части:")
            for i in range(0, len(response_message), MAX_MESSAGE_LENGTH):
                await update.message.reply_html(response_message[i:i + MAX_MESSAGE_LENGTH])
        else:
            await update.message.reply_html(response_message)

        logger.info(f"User {user.id} viewed their submissions. Count: {len(submissions_list)}")

    except Exception as e:
        logger.error(f"Error fetching submissions for user {user.id}: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка при загрузке ваших заявок.")
    finally:
        if db_gen:
            try:
                await db_gen.aclose()
            except Exception as gen_close_exc:
                logger.error(f"Error closing db_gen in my_submissions: {gen_close_exc}", exc_info=True)


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
        "Я бот для сбора ваших жалоб и просьб.\n\n"
        "<b>Основные команды:</b>\n"
        "/start - начать процесс подачи жалобы или просьбы.\n"
        "/my_submissions - посмотреть список ваших предыдущих заявок и их статусы.\n"
        "/cancel - отменить текущее действие (например, если вы передумали писать жалобу).\n"
        "/help - показать это сообщение.\n\n"
        "<b>Как подать заявку:</b>\n"
        "1. Введите /start.\n"
        f"2. Напишите '{COMPLAINT_KEYWORD_RU}' для жалобы или '{REQUEST_KEYWORD_RU}' для просьбы.\n"
        "3. Следуйте инструкциям бота и опишите вашу ситуацию.\n"
        "После отправки заявка будет зарегистрирована."
    )
    await update.message.reply_html(help_text)

def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Токен TELEGRAM_BOT_TOKEN не найден в .env файле")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    keywords_regex = f"^({COMPLAINT_KEYWORD_RU}|{REQUEST_KEYWORD_RU})$"

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(keywords_regex), choose_action),
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_action)
            ],
            GET_COMPLAINT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_submission)
            ],
            GET_REQUEST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_submission)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start)
        ],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("my_submissions", my_submissions_command))

    logger.info("Бот запускается...")
    application.run_polling()

if __name__ == "__main__":
    main()