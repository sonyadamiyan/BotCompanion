import telebot
import logging
from telebot.types import ReplyKeyboardMarkup
from config import COUNT_LAST_MSG
from creds import get_bot_token
from database import create_database, add_message, select_n_last_messages
from validators import check_number_of_users, is_stt_block_limit, is_gpt_token_limit, is_tts_symbol_limit
from yandex_gpt import LOGS, ask_gpt
from speechkit import text_to_speech, speech_to_text
bot = telebot.TeleBot(get_bot_token())
logging.basicConfig(filename=LOGS, level=logging.ERROR, format="%(asctime)s FILE: %(filename)s IN: %(funcName)s MESSAGE: %(message)s", filemode="w")


def create_keyboard(buttons_list):
    keyboard = ReplyKeyboardMarkup(
        row_width=1,
        resize_keyboard=True
    )
    keyboard.add(*buttons_list)


@bot.message_handler(commands=['start'])
def start(message: telebot.types.Message):
    create_database()
    bot.send_message(message.from_user.id,
                     text="Привет!\n"
                     "Я могу ответить на любой твой вопрос или просто поболтать\n"
                     "Присылаю ответ в том же формате, в котором ты присылал запрос:\n"
                     "(текст в ответ на текст, голос в ответ на голос)")


@bot.message_handler(commands=['debug'])
def debug(message: telebot.types.Message):
    with open(LOGS, "rb") as f:
        bot.send_document(message.chat.id, f)


@bot.message_handler(commands=['tts'])
def tts_handler(message: telebot.types.Message):
    user_id = message.from_user.id
    bot.send_message(user_id,
                     text="Напиши текст,который хочешь озвучить\n"
                     "на русском или анлийском языках")
    bot.register_next_step_handler(message, start_tts)


def start_tts(message: telebot.types.Message):
    user_id = message.from_user.id
    text = message.text
    if message.content_type != 'text':
        bot.send_message(user_id, 'Отправь текстовое сообщение')
        bot.register_next_step_handler(message, start_tts)
        return

    tts_symbols, error_message = is_tts_symbol_limit(user_id, text)
    if error_message:
        bot.send_message(user_id, error_message)
        return

    status, content = text_to_speech(text)
    if status:
        bot.send_voice(user_id, content, reply_to_message_id=message.id)
    else:
        bot.send_message(user_id, content)


@bot.message_handler(commands=['stt'])
def stt_handler(message: telebot.types.Message):
    user_id = message.from_user.id
    bot.send_message(user_id, 'Запиши голосовое сообщение, которое хочешь превратить в текст')
    bot.register_next_step_handler(message, start_stt)


def start_stt(message: telebot.types.Message):
    user_id = message.from_user.id
    if not message.voice:
        bot.send_message(user_id,
                         text='Запиши голосовое сообщение, которое хочешь превратить в текст')
        bot.register_next_step_handler(message, start_stt)
        return

    stt_blocks, error_message = is_stt_block_limit(user_id, message.voice.duration)
    if error_message:
        bot.send_message(user_id, error_message)
        return
    file_id = message.voice.file_id
    file_info = bot.get_file(file_id)
    file = bot.download_file(file_info.file_path)

    status, text = speech_to_text(file)
    if status:
        bot.send_message(user_id, text, reply_to_message_id=message.id)
    else:
        bot.send_message(user_id, text)


@bot.message_handler(content_types=['voice'])
def handle_voice(message: telebot.types.Message):
    try:
        user_id = message.from_user.id
        status_check_users, error_message = check_number_of_users(user_id)
        if not status_check_users:
            bot.send_message(user_id, error_message)
            return

        stt_blocks, error_message = is_stt_block_limit(user_id, message.voice.duration)
        if error_message:
            bot.send_message(user_id, error_message)
            return

        file_id = message.voice.file_id
        file_info = bot.get_file(file_id)
        file = bot.download_file(file_info.file_path)
        status_stt, stt_text = speech_to_text(file)
        if not status_stt:
            bot.send_message(user_id, stt_text)
            return

        add_message(user_id=user_id, full_message=[stt_text, 'user', 0, 0, stt_blocks])

        last_messages, total_spent_tokens = select_n_last_messages(user_id, COUNT_LAST_MSG)
        total_gpt_tokens, error_message = is_gpt_token_limit(last_messages, total_spent_tokens)
        if error_message:
            bot.send_message(user_id, error_message)
            return

        status_gpt, answer_gpt, tokens_in_answer = ask_gpt(last_messages)
        if not status_gpt:
            bot.send_message(user_id, answer_gpt)
            return
        total_gpt_tokens += tokens_in_answer

        tts_symbols, error_message = is_tts_symbol_limit(user_id, answer_gpt)

        add_message(user_id=user_id, full_message=[answer_gpt, 'assistant', total_gpt_tokens, tts_symbols, 0])
        if error_message:
            bot.send_message(user_id, error_message)
            return

        status_tts, voice_response = text_to_speech(answer_gpt)
        if status_tts:
            bot.send_voice(user_id, voice_response, reply_to_message_id=message.id)
        else:
            bot.send_message(user_id, answer_gpt, reply_to_message_id=message.id)

    except Exception as e:
        logging.error(e)
        bot.send_message(message.from_user.id,
                         text="Ошибка :( Попробуй ещё раз")


@bot.message_handler(content_types=['text'])
def handle_text(message):
    try:
        user_id = message.from_user.id

        status_check_users, error_message = check_number_of_users(user_id)
        if not status_check_users:
            bot.send_message(user_id, error_message)
            return

        full_user_message = [message.text, 'user', 0, 0, 0]
        add_message(user_id=user_id, full_message=full_user_message)

        last_messages, total_spent_tokens = select_n_last_messages(user_id, COUNT_LAST_MSG)
        total_gpt_tokens, error_message = is_gpt_token_limit(last_messages, total_spent_tokens)
        if error_message:
            bot.send_message(user_id, error_message)
            return

        status_gpt, answer_gpt, tokens_in_answer = ask_gpt(last_messages)
        if not status_gpt:
            bot.send_message(user_id, answer_gpt)
            return
        total_gpt_tokens += tokens_in_answer
        full_gpt_message = [answer_gpt, 'assistant', total_gpt_tokens, 0, 0]
        add_message(user_id=user_id, full_message=full_gpt_message)

        bot.send_message(user_id, answer_gpt, reply_to_message_id=message.id)
    except Exception as e:
        logging.error(e)
        bot.send_message(message.from_user.id,
                         text="Ошибка :( Попробуй ещё раз")


@bot.message_handler(func=lambda: True)
def handler(message):
    bot.send_message(message.from_user.id,
                     text="Отправь мне голосовое или текстовое сообщение, и я тебе отвечу")


bot.polling()
