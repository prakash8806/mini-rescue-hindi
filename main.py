import os
import sys
import json
import random
import datetime
import time
import urllib.request
import urllib.parse
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from gtts import gTTS
import edge_tts
import asyncio
from moviepy import ImageClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
import googleapiclient.discovery
import googleapiclient.http
from google.oauth2.credentials import Credentials

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN")

genai.configure(api_key=GEMINI_API_KEY)

# --- STEP 1: GENERATE ORIGINAL STORY & SCRIPT WITH MULTI-MODEL FALLBACK ---
def generate_story():
    # एकामागून एक ट्राय करण्यासाठी वेगवेगळ्या मॉडेल्सची लिस्ट
    models_to_try = ['gemini-2.5-flash', 'gemini-3.5-flash', 'gemini-3.8-flash']
    
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
    Return ONLY valid JSON. No markdown ticks around it if possible, or parse cleanly.
    """
    
    for model_name in models_to_try:
        try:
            print(f"🤖 मॉडेल वापरत आहे: {model_name}...")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
        except ResourceExhausted:
            print(f"⚠️ {model_name} चा कोटा संपला आहे (429). पुढच्या मॉडेलवर स्विच करत आहे...")
            time.sleep(5) # ५ सेकंद थांबून पुढचे मॉडेल ट्राय करेल
        except Exception as e:
            print(f"⚠️ {model_name} मध्ये एरर आली: {e}. पुढच्या मॉडेलकडे जात आहे...")
            
    raise Exception("सर्वच्या सर्व मॉडेल्सचे (Gemini Models) कोटे संपले आहेत किंवा रिस्पॉन्स मिळाला नाही.")

# --- STEP 2: GENERATE VOICE (EDGE TTS) ---
async def generate_voiceover(text_list, output_path="voiceover.mp3"):
    full_text = " ".join(text_list)
    communicate = edge_tts.Communicate(full_text, "hi-IN-SwaraNeural")
    await communicate.save(output_path)

# --- STEP 3: GENERATE IMAGE ASSETS (FREE & RELIABLE) ---
def fetch_image(prompt, output_filename):
    try:
        # आपण DeepAI चा फ्री टेक्स्ट-टू-इमेज URL किंवा Picsum वापरू शकतो
        # सध्या आपण अतिशय सुंदर आणि पूर्णपणे फ्री Picsum/Unsplash स्टाईल किंवा फ्री डमी इमेज वापरत आहोत
        # जेणेकरून कोणत्याही पैशांची किंवा एररची अडचण येणार नाही.
        
        # पर्यायी मोफत इमेज सर्व्हर (որտեղ payment ची गरज नाही)
        encoded_prompt = urllib.parse.quote(prompt[:100])
        url = f"https://picsum.photos/seed/{random.randint(1, 10000)}/1080/1920"
        
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req) as response, open(output_filename, 'wb') as out_file:
            out_file.write(response.read())
            
        print(f"✅ इमेज यशस्वीरित्या तयार झाली: {output_filename}")
    except Exception as e:
        print(f"⚠️ इमेज जनरेट करताना अडचण आली: {e}")
        # इमर्जन्सीसाठी साधी रँडम इमेज सेव्ह करेल जेणेकरून व्हिडिओ रेंडरिंग थांबणार नाही
        fallback_url = f"https://picsum.photos/1080/1920"
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
        fetch_image(scene["visual"], img_path)
        
        # MoviePy v2.x साठी with_duration आणि resized वापरले आहे
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
    print(f"Uploaded successfully! Video ID: {response.get('id')}")

async def main():
    print("--- Starting Daily Mini Rescue Hindi Automation ---")
    story = generate_story()
    print(f"Story Generated: {story['title']}")
    
    narrations = [s["narration"] for s in story["scenes"]]
    await generate_voiceover(narrations, "voice.mp3")
    print("Voiceover generated.")
    
    video_path = create_video(story, "voice.mp3")
    print("Video rendered successfully.")
    
    upload_to_youtube(video_path, story["title"] + " #Shorts", story["description"])
    print("Publishing complete!")

if __name__ == "__main__":
    asyncio.run(main())
