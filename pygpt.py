import os
import uuid
import time
import subprocess
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import yt_dlp

# إعداد المتغيرات الأساسية
TOKEN = "7336372322:AAEtIUcY6nNEEGZzIMjJdfYMTAMsLpTSpzk"
PORT = int(os.environ.get("PORT", 10000))

app = Flask(__name__)

@app.route("/")
def home():
    return "البوت يعمل!", 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

def get_available_formats(url):
    try:
        ydl_opts = {
            'cookiefile': 'cookies.txt',
            'ignoreerrors': True,
            'retries': 10,
            'sleep_interval': 60,
            'ratelimit': 500000,
            'http_headers': {'User-Agent': 'Mozilla/5.0'},
            'format_sort': ['res:2160', 'res:1080', 'mp4'],
            'extract_flat': 'in_playlist',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # التحقق من صلاحية المحتوى
            if not info or info.get('availability') != 'public':
                return None
                
            formats = info.get('formats') or []
            available_formats = []
            
            for f in formats:
                if f.get('vcodec') == 'none' or f.get('acodec') == 'none':
                    continue
                    
                # دعم خاص لفيسبوك
                if 'facebook' in url.lower():
                    if f.get('format_id') in ['hd', 'sd', 'dav']:
                        available_formats.append({
                            'format_id': f['format_id'],
                            'resolution': f.get('resolution', 'Unknown'),
                            'ext': f.get('ext', 'mp4')
                        })
                else:
                    available_formats.append({
                        'format_id': f['format_id'],
                        'resolution': f.get('resolution', f.get('format_note', 'Unknown')),
                        'ext': f.get('ext', 'mp4')
                    })
                    
            available_formats.sort(key=lambda x: int(x['resolution'].replace('p', '')) if 'p' in x['resolution'] else 0, reverse=True)
            return available_formats[:10]
            
    except Exception as e:
        print(f"Critical Error: {str(e)}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('مرحبا! أرسل رابط فيديو من يوتيوب أو فيسبوك وسأحمله لك.')

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    try:
        # معالجة روابط فيسبوك
        if "facebook" in url.lower():
            url = url.replace("www.facebook.com", "fb.watch").replace("m.facebook.com", "fb.watch")
            await update.message.reply_text("⚠️ جاري معالجة فيديو فيسبوك... قد يستغرق هذا بعض الوقت")
        
        formats = get_available_formats(url)
        if not formats:
            await update.message.reply_text("⚠️ لم أجد جودات متاحة. تأكد من:\n1. الرابط صحيح\n2. المحتوى عام\n3. تحديث cookies.txt")
            return
            
        keyboard = [
            [InlineKeyboardButton(f"{f['resolution']} ({f['ext']})", callback_data=f['format_id'])]
            for f in formats
        ]
        
        await update.message.reply_text(
            "اختر جودة الفيديو:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data['url'] = url
        
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)[:200]}")

async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        format_id = query.data
        url = context.user_data.get('url')
        if not url:
            raise ValueError("الرابط مفقود")
        
        unique_id = str(uuid.uuid4())
        temp_filename = f"temp_{unique_id}.%(ext)s"
        final_filename = f"video_{unique_id}.mp4"
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': temp_filename,
            'merge_output_format': 'mp4',
            'retries': 10,
            'sleep_interval': 60,
            'ratelimit': 500000,
            'cookiefile': 'cookies.txt',
            'http_headers': {'User-Agent': 'Mozilla/5.0'},
            'prefer_free_formats': True,
            'quiet': True,
            'extract_flat': 'in_playlist',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            temp_filename = ydl.prepare_filename(info)
            
            # دمج الأجزاء إذا لزم الأمر
            if not temp_filename.endswith('.mp4'):
                subprocess.run(['ffmpeg', '-i', temp_filename, '-c', 'copy', final_filename])
                os.remove(temp_filename)
                temp_filename = final_filename
                
        # التحقق من حجم الملف
        if os.path.exists(temp_filename):
            file_size = os.path.getsize(temp_filename)
            if file_size > 2 * 1024 * 1024 * 1024:  # 2GB
                await query.edit_message_text("⚠️ الفيديو كبير جدًا! حاول اختيار جودة أقل.")
                return
                
            with open(temp_filename, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=video_file,
                    caption="تم التحميل بواسطتنا 🎥",
                    read_timeout=600,
                    write_timeout=600,
                    connect_timeout=600,
                    supports_streaming=True
                )
                
            await query.edit_message_text("✅ تم الإرسال بنجاح!")
        else:
            await query.edit_message_text("❌ خطأ: الملف غير موجود!")
            
    except yt_dlp.utils.DownloadError as e:
        await query.edit_message_text(f"⚠️ خطأ تحميل: {str(e)[:200]}")
    except telegram.error.BadRequest as e:
        if "File too large" in str(e):
            await query.edit_message_text("⚠️ الفيديو كبير جدًا للإرسال! حاول جودة أقل.")
        else:
            await query.edit_message_text(f"⚠️ خطأ: {str(e)[:200]}")
    except Exception as e:
        await query.edit_message_text(f"❌ خطأ عام: {str(e)[:200]}")
    finally:
        if 'temp_filename' in locals() and os.path.exists(temp_filename):
            os.remove(temp_filename)

def main():
    Thread(target=run_flask, daemon=True).start()
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(download_video))
    
    application.run_polling()

if __name__ == '__main__':
    main()
