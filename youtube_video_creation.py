import os
import sys
import json
import random
import datetime
import time
import urllib.request
import urllib.parse
from groq import Groq
from gtts import gTTS
import edge_tts
import asyncio
from moviepy import ImageClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
import googleapiclient.discovery
import googleapiclient.http
from google.oauth2.credentials import Credentials
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- CONFIGURATION ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN")

client = Groq(api_key=GROQ_API_KEY)

# --- STEP 1: GENERATE ORIGINAL STORY & SCRIPT USING GROQ ---
def generate_story():
    print("🤖 Groq मॉडेल वापरत आहे (Llama 3)...")
    prompt = """
    You are a children's cartoon director. Create a brand new, original 45-second animal rescue story in Hindi for YouTube Shorts.
    Characters: Chhotu (Baby Elephant in blue uniform), Bunty (Rabbit in yellow shirt), Goldie (Puppy in red collar), Young Rescuer (Boy in red jacket).
    Theme: Forest or river rescue with a happy ending and moral lesson.
    Output MUST be a JSON object with EXACT keys:
    {
      "title": "Catchy YouTube Short Title in Hindi with emojis",
      "description": "SEO description with hashtags",
      "scenes": [
        {"narration": "Hindi sentence 1 for scene 1", "visual": "Detailed prompt for image generation"},
        {"narration": "Hindi sentence 2 for scene 2", "visual": "Detailed prompt for image generation"},
        {"narration": "Hindi sentence 3 for scene 3", "visual": "Detailed prompt for image generation"},
        {"narration": "Hindi sentence 4 for scene 4", "visual": "Detailed prompt for image generation"},
        {"narration": "Hindi sentence 5 for scene 5 (Moral lesson)", "visual": "Detailed prompt for image generation"}
      ]
    }
    Return ONLY valid JSON.
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",  # हे मॉडेल सर्व Groq अकाउंट्सवर उपलब्ध असते आणि सुपरफास्ट चालते
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs JSON only."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        text = completion.choices[0].message.content.strip()
        return json.loads(text)
    except Exception as e:
        print(f"⚠️ Groq API मध्ये एरर आली: {e}")
        raise Exception("Groq कडून रिस्पॉन्स मिळाला नाही.")

# --- STEP 2: GENERATE VOICE (EDGE TTS) ---
async def generate_voiceover(text_list, output_path="voiceover.mp3"):
    full_text = " ".join(text_list)
    communicate = edge_tts.Communicate(full_text, "hi-IN-SwaraNeural")
    await communicate.save(output_path)

# --- STEP 3: GENERATE AI CARTOON IMAGES ---
def fetch_image(prompt, output_filename, scene_index=0):
    cartoon_prompt = f"3D Disney Pixar style cute cartoon animation, bright colors, children book illustration: {prompt}"
    encoded_prompt = urllib.parse.quote(cartoon_prompt)
    
    ai_image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true&seed={random.randint(1, 999999)}"
    
    try:
        req = urllib.request.Request(
            ai_image_url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=30) as response, open(output_filename, 'wb') as out_file:
            out_file.write(response.read())
        print(f"🎨 एआय कार्टून इमेज यशस्वीरित्या तयार झाली [{scene_index}]: {output_filename}")
    except Exception as e:
        print(f"⚠️ एआय इमेज बनवताना एरर आली ({e}), बॅकअप इमेज वापरत आहे...")
        fallback_url = f"https://picsum.photos/seed/cartoon_{scene_index}/1080/1920"
        urllib.request.urlretrieve(fallback_url, output_filename)

# --- STEP 4: ASSEMBLE VIDEO WITH MOVIEPY ---
def create_video(story_data, audio_path, output_video="final_short.mp4"):
    scenes = story_data["scenes"]
    audio_clip = AudioFileClip(audio_path)
    total_duration = audio_clip.duration
    duration_per_scene = total_duration / len(scenes)
    
    clips = []
    for i, scene in enumerate(scenes):
        img_path = f"scene_{i}.jpg"
        fetch_image(scene["visual"], img_path, scene_index=i)
        
        clip = ImageClip(img_path).with_duration(duration_per_scene)
        clip = clip.resized(height=1920)
        clips.append(clip)
        
    video = concatenate_videoclips(clips, method="compose")
    video = video.with_audio(audio_clip)
    video.write_videofile(output_video, fps=24, codec="libx264", audio_codec="aac")
    return output_video

# --- STEP 5: UPLOAD TO YOUTUBE ---
def upload_to_youtube(video_file, title, description):
    creds = Credentials(
        None,
        refresh_token=YT_REFRESH_TOKEN,
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token"
    )
    youtube = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
    
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": ["mini rescue hindi", "animal rescue", "kids cartoons", "shorts"],
            "categoryId": "1"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": True
        }
    }
    
    media = googleapiclient.http.MediaFileUpload(video_file, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    video_id = response.get('id')
    print(f"Uploaded successfully! Video ID: {video_id}")
    return video_id

# --- STEP 6: EMAIL NOTIFICATION FUNCTION ---
def send_email_notification(video_title, video_id):
    sender_email = os.environ.get("SENDER_EMAIL")
    app_password = os.environ.get("EMAIL_APP_PASSWORD")
    
    if not sender_email or not app_password:
        print("⚠️ Email credentials सापडले नाहीत, त्यामुळे मेल पाठवला नाही.")
        return

    receiver_email = sender_email
    
    message = MIMEMultipart("alternative")
    message["Subject"] = "🚀 नवीन YouTube Short यशस्वीरित्या अपलोड झाला!"
    message["From"] = sender_email
    message["To"] = receiver_email
    
    video_link = f"https://youtu.be/{video_id}"
    
    html = f"""
    <html>
      <body>
        <h2>🎉 अभिनंदन! तुमचे ऑटोमेशन यशस्वी झाले आहे.</h2>
        <p>तुमचा नवीन युट्यूब शॉर्ट्स व्हिडिओ यशस्वीरित्या युट्यूबवर पब्लिश झाला आहे.</p>
        <p><b>शीर्षक (Title):</b> {video_title}</p>
        <p><b>पाहण्यासाठी येथे क्लिक करा:</b> <a href="{video_link}">व्हिडिओ पहा</a></p>
      </body>
    </html>
    """
    
    message.attach(MIMEText(html, "html"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, receiver_email, message.as_string())
        print("📧 ईमेल नोटिफिकेशन यशस्वीरित्या पाठवली आहे!")
    except Exception as e:
        print(f"⚠️ ईमेल पाठवताना एरर आली: {e}")

async def main():
    print("--- Starting Daily Mini Rescue Hindi Automation ---")
    story = generate_story()
    print(f"Story Generated: {story['title']}")
    
    narrations = [s["narration"] for s in story["scenes"]]
    await generate_voiceover(narrations, "voice.mp3")
    print("Voiceover generated.")
    
    video_path = create_video(story, "voice.mp3")
    print("Video rendered successfully.")
    
    video_id = upload_to_youtube(video_path, story["title"] + " #Shorts", story["description"])
    print("Publishing complete!")
    
    send_email_notification(story['title'], video_id)

if __name__ == "__main__":
    asyncio.run(main())
