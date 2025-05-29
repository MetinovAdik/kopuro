import os
import time
from datetime import datetime, timezone

import requests
import schedule
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from database import SessionLocal, get_db, Base, engine
from models import YoutubeComment, CommentSentiment
load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_IDS = [
    "UCMT_crm-eLZl3CNvNr-1lWQ",  # Ала Тоо
    "UCbj2FCkrX13P9fDnxnY0GGw",  # Апрель
    "UCwlDbu6R30KrhDxq0ETTXPQ"  # Лимон KG
    "UCNPxzbEkoNcydfLrRdTb-HA"  # Акипресс
    "UCs_xNajKMU60fbeIhcxStoA"  # Азаттык

]

VIDEOS_PER_CHANNEL = 10
MAX_COMMENTS_PER_VIDEO = 100
# --------------------

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
AI_MODEL_ENDPOINT = "http://localhost:11434/api/generate"
AI_MODEL_NAME = "gemma3:27b"  # или ваша модель
SENTIMENT_CACHE = {}

RUN_EVERY_MINUTES = 60


def create_db_tables():
    try:
        print("Проверка и создание таблиц базы данных...")
        Base.metadata.create_all(bind=engine)
        print("Таблицы успешно проверены/созданы.")
    except Exception as e:
        print(f"Ошибка при создании таблиц: {e}")
        # exit(1)


def get_youtube_service():
    try:
        service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=API_KEY)
        return service
    except Exception as e:
        print(f"Ошибка при инициализации YouTube сервиса: {e}")
        return None


def get_channel_uploads_playlist_id(youtube, channel_id):
    try:
        request = youtube.channels().list(part="contentDetails,snippet", id=channel_id)
        response = request.execute()
        if response["items"]:
            channel_title = response["items"][0]["snippet"]["title"]
            uploads_playlist_id = response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            return uploads_playlist_id, channel_title
        else:
            print(f"Канал с ID {channel_id} не найден.")
            return None, None
    except HttpError as e:
        print(f"Ошибка API при получении ID плейлиста для канала {channel_id}: {e}")
        return None, None
    except Exception as e:
        print(f"Неожиданная ошибка при получении ID плейлиста для канала {channel_id}: {e}")
        return None, None


def get_video_ids_from_playlist(youtube, playlist_id, channel_title, max_results=10):
    video_ids = []
    try:
        request = youtube.playlistItems().list(part="contentDetails", playlistId=playlist_id,
                                               maxResults=min(max_results, 50))
        response = request.execute()
        for item in response["items"]:
            video_ids.append(item["contentDetails"]["videoId"])
            if len(video_ids) >= max_results:
                break
        return video_ids
    except HttpError as e:
        print(f"Ошибка API при получении видео из плейлиста {playlist_id}: {e}")
        return []
    except Exception as e:
        print(f"Неожиданная ошибка при получении видео из плейлиста {playlist_id}: {e}")
        return []


def get_video_details(youtube, video_id):
    try:
        request = youtube.videos().list(part="snippet", id=video_id)
        response = request.execute()
        if response["items"]:
            return response["items"][0]
        else:
            print(f"Видео с ID {video_id} не найдено.")
            return None
    except HttpError as e:
        print(f"Ошибка API при получении деталей видео {video_id}: {e}")
        return None
    except Exception as e:
        print(f"Неожиданная ошибка при получении деталей видео {video_id}: {e}")
        return None


def get_video_comments(youtube, video_id, video_title, max_results=20):
    comments_data_list = []
    next_page_token = None
    try:
        while True:
            request = youtube.commentThreads().list(
                part="snippet", videoId=video_id,
                maxResults=min(max_results - len(comments_data_list), 100),
                textFormat="plainText", pageToken=next_page_token, order="relevance"
            )
            response = request.execute()
            for item in response["items"]:
                comment_snippet = item["snippet"]["topLevelComment"]["snippet"]
                published_at_str = comment_snippet.get("publishedAt")
                published_at_dt = None
                if published_at_str:
                    try:
                        published_at_dt = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                    except ValueError:
                        print(f"    Не удалось распознать дату комментария: {published_at_str}")

                comments_data_list.append({
                    "youtube_comment_id": item["id"],
                    "author_username": comment_snippet["authorDisplayName"],
                    "comment_text": comment_snippet["textDisplay"],
                    "published_at": published_at_dt,
                })
                if len(comments_data_list) >= max_results: break
            next_page_token = response.get("nextPageToken")
            if not next_page_token or len(comments_data_list) >= max_results: break
        return comments_data_list
    except HttpError as e:
        if e.resp.status == 403 and 'commentsDisabled' in str(e.content):
            print(f"  Комментарии для видео '{video_title}' (ID: {video_id}) отключены.")
        elif e.resp.status == 403:
            print(f"  Доступ к комментариям для видео '{video_title}' (ID: {video_id}) запрещен (403).")
        else:
            print(f"  Ошибка API при получении комментариев для видео '{video_title}' (ID: {video_id}): {e}")
        return []
    except Exception as e:
        print(f"  Неожиданная ошибка при получении комментариев для видео '{video_title}' (ID: {video_id}): {e}")
        return []


def analyze_comment_sentiment_with_ai(comment_text: str):
    stripped_text = comment_text.strip()
    if not stripped_text: return CommentSentiment.NEUTRAL
    if stripped_text in SENTIMENT_CACHE: return SENTIMENT_CACHE[stripped_text]

    prompt = f"""Вы — эксперт по классификации эмоциональной окраски текста. Проанализируйте следующий комментарий с YouTube и определите его эмоциональный тон.
Выберите одну метку из следующих категорий: ПОЗИТИВНЫЙ, НЕГАТИВНЫЙ, НЕЙТРАЛЬНЫЙ, РАЗОЧАРОВАННЫЙ, ЗЛОЙ, ВОСТОРЖЕННЫЙ, ГРУСТНЫЙ, БЛАГОДАРНЫЙ, НЕДОУМЕВАЮЩИЙ, САРКАСТИЧНЫЙ
Комментарий: "{stripped_text}"
Ответьте только меткой."""
    try:
        response = requests.post(AI_MODEL_ENDPOINT, json={"model": AI_MODEL_NAME, "prompt": prompt, "stream": False},
                                 timeout=90)
        if response.status_code == 200:
            ai_response_raw = response.json().get("response", "").strip()
            ai_response_value = ai_response_raw.upper()
            sentiment_enum_val = CommentSentiment.UNKNOWN
            try:
                sentiment_enum_val = CommentSentiment(ai_response_value)
            except ValueError:
                print(f"    ИИ вернул неизвестный тег: '{ai_response_raw}'. Установлено НЕОПРЕДЕЛЕНО.")
                sentiment_enum_val = CommentSentiment.UNKNOWN
            SENTIMENT_CACHE[stripped_text] = sentiment_enum_val
            return sentiment_enum_val
        else:
            print(f"    Ошибка от сервиса ИИ ({response.status_code}): {response.text}")
            SENTIMENT_CACHE[stripped_text] = CommentSentiment.UNKNOWN
            return CommentSentiment.UNKNOWN
    except requests.exceptions.RequestException as e:
        print(f"    Ошибка соединения с сервисом ИИ: {e}")
    except Exception as e:
        print(f"    Неожиданная ошибка во время анализа ИИ: {e}")
    SENTIMENT_CACHE[stripped_text] = CommentSentiment.UNKNOWN  # Кэшируем ошибку как UNKNOWN
    return CommentSentiment.UNKNOWN


def process_new_youtube_data():
    print(f"[{datetime.now()}] Запуск задачи мониторинга YouTube...")
    youtube = get_youtube_service()
    if not youtube:
        print(f"[{datetime.now()}] Не удалось инициализировать YouTube сервис. Пропуск цикла.")
        return

    db_session_gen = get_db()
    db = next(db_session_gen)
    processed_videos_count = 0
    new_comments_count = 0

    try:
        for channel_id_to_monitor in CHANNEL_IDS:
            uploads_playlist_id, current_channel_title_api = get_channel_uploads_playlist_id(youtube,
                                                                                             channel_id_to_monitor)
            if not uploads_playlist_id:
                print(f"Не удалось получить плейлист для канала {channel_id_to_monitor}. Пропускаем.")
                continue
            print(f"Канал: '{current_channel_title_api}' (ID: {channel_id_to_monitor})")

            video_ids = get_video_ids_from_playlist(youtube, uploads_playlist_id, current_channel_title_api,
                                                    VIDEOS_PER_CHANNEL)
            if not video_ids: continue

            for i, video_id in enumerate(video_ids, 1):
                video_details_response = get_video_details(youtube, video_id)
                if not video_details_response: continue

                processed_videos_count += 1
                video_title = video_details_response["snippet"]["title"]
                video_channel_id_api = video_details_response["snippet"]["channelId"]
                video_channel_title_api = video_details_response["snippet"]["channelTitle"]
                default_topic_for_video = video_title

                comments_list = get_video_comments(youtube, video_id, video_title, MAX_COMMENTS_PER_VIDEO)
                if not comments_list: continue

                current_video_new_comments = 0
                for comment_data in comments_list:
                    existing_comment = db.query(YoutubeComment).filter_by(
                        youtube_comment_id=comment_data["youtube_comment_id"]).first()
                    if existing_comment: continue

                    analyzed_sentiment = analyze_comment_sentiment_with_ai(comment_data["comment_text"])
                    new_db_comment = YoutubeComment(
                        youtube_username=comment_data["author_username"],
                        comment_text=comment_data["comment_text"],
                        youtube_comment_id=comment_data["youtube_comment_id"],
                        youtube_video_id=video_id,
                        youtube_channel_id=video_channel_id_api,
                        youtube_channel_title=video_channel_title_api,
                        comment_published_at=comment_data["published_at"],
                        topic=default_topic_for_video,
                        opinion_text=None,
                        sentiment=analyzed_sentiment
                    )
                    db.add(new_db_comment)
                    new_comments_count += 1
                    current_video_new_comments += 1

                if current_video_new_comments > 0:
                    print(
                        f"    Для видео '{video_title[:50]}...' добавлено {current_video_new_comments} новых комментариев.")

                if current_video_new_comments > 0:
                    try:
                        db.commit()
                    except Exception as e_commit:
                        print(f"Ошибка при коммите для видео '{video_title[:50]}...': {e_commit}")
                        db.rollback()

        print(f"\n[{datetime.now()}] Задача мониторинга YouTube завершена.")
        print(f"Обработано видео: {processed_videos_count}, Добавлено новых комментариев: {new_comments_count}")

    except Exception as e:
        print(f"Произошла глобальная ошибка в задаче мониторинга: {e}")
        if db.is_active: db.rollback()
    finally:
        if db.is_active: db.close()


if __name__ == "__main__":
    if API_KEY == "AIzaSyDFVqojCYx50An" or API_KEY == "ВАШ_API_КЛЮЧ":
        print("ПОЖАЛУЙСТА, УКАЖИТЕ ВАШ ДЕЙСТВИТЕЛЬНЫЙ YouTube API_KEY В СКРИПТЕ.")
        exit(1)
    if not CHANNEL_IDS:
        print("Пожалуйста, укажите хотя бы один CHANNEL_ID в списке CHANNEL_IDS.")
        exit(1)

    create_db_tables()

    print(f"Планировщик настроен на запуск задачи каждые {RUN_EVERY_MINUTES} минут.")
    print("Первый запуск задачи мониторинга...")
    process_new_youtube_data()

    schedule.every(RUN_EVERY_MINUTES).minutes.do(process_new_youtube_data)

    print("Скрипт запущен. Для остановки нажмите Ctrl+C.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nПолучен сигнал прерывания. Завершение работы...")
    except Exception as e:
        print(f"Непредвиденная ошибка в основном цикле: {e}")
    finally:
        print("Скрипт остановлен.")