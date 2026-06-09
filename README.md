# Gemma 4 E4B - Local AI Assistant

AI Assistant ที่รันบนเครื่องตัวเอง ไม่ต้องใช้ internet ไม่มีค่า API ข้อมูลไม่หลุดออกนอกเครื่อง

ใช้ [Gemma 4 E4B](https://ai.google.dev/gemma) ผ่าน [Ollama](https://ollama.com/) + [Gradio](https://gradio.app/) Web UI

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Ollama](https://img.shields.io/badge/Ollama-required-green)
![RAM](https://img.shields.io/badge/RAM-4GB+-orange)

## Features

- **Chat-based AI Assistant** - คุยภาษาไทย/อังกฤษได้
- **4 Tools** - รัน command, อ่าน/เขียนไฟล์, รัน Python script
- **Permission Controls** - Full Auto / Safe Mode / Chat Only
- **Sliding Window Context** - ทำงานหลายขั้นตอนได้ไม่ล้น
- **Auto-inject Notes** - AI ใช้ไฟล์เป็น memory ภายนอก
- **Chat History** - Save/Load/Delete บทสนทนา
- **Summary System** - สรุป context ไว้ใช้ข้ามบทสนทนา
- **Stop & Continue** - หยุดได้ ทำต่อได้

## Requirements

- **Windows 10/11**
- **Python 3.10+** ([python.org](https://www.python.org/downloads/))
- **Ollama** ([ollama.com](https://ollama.com/download))
- **RAM 4GB+** (ใช้ quantized model Q4)

## Quick Start

### 1. Install Ollama

ดาวน์โหลดจาก [ollama.com](https://ollama.com/download) แล้วติดตั้ง

### 2. Download Model

ดาวน์โหลดไฟล์ GGUF แล้ววางในโฟลเดอร์นี้:

```
Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q4_K_P.gguf
```

> ดาวน์โหลดจาก HuggingFace: ค้นหา "Gemma 4 E4B Uncensored GGUF"
>
> หรือใช้ model อื่นได้ แก้ชื่อไฟล์ใน `Modelfile` บรรทัด `FROM ./...`

### 3. Start

```bash
# Double-click หรือรันใน terminal:
start.bat
```

จะเปิด browser ที่ `http://localhost:7860` อัตโนมัติ

### 4. Stop

```bash
stop.bat
```

## Usage

### Chat ปกติ
พิมพ์ข้อความแล้ว Enter ได้เลย AI ตอบเป็นภาษาไทยหรืออังกฤษตามที่ถาม

### สั่ง AI ทำงาน
```
เปิด notepad
อ่านไฟล์ app.py
สร้างไฟล์ hello.py ที่ print Hello World
รัน dir /b ดูไฟล์ในโฟลเดอร์นี้
สรุป project ใน D:\Works\MyProject
```

### Permission Levels

| Mode | รัน Command | อ่านไฟล์ | เขียนไฟล์ | รัน Python |
|------|:---------:|:-------:|:--------:|:---------:|
| **Full Auto** | auto | auto | auto | auto |
| **Safe Mode** | auto | auto | ask | ask |
| **Chat Only** | - | - | - | - |

## Project Structure

```
├── app.py           # Main application (Gradio UI + Agent loop)
├── Modelfile        # Ollama model config + system prompt
├── start.bat        # Start script (Ollama + Gradio)
├── stop.bat         # Stop script (free VRAM)
├── requirements.txt # Python dependencies
└── chats/           # Saved chat history (auto-created)
```

## How It Works

```
User message
    ↓
Ollama (Gemma 4B) generates response
    ↓
Extract action tags: <cmd>, <read>, <write>, <python>
    ↓
Execute actions → feed results back to model
    ↓
Repeat until task is done (sliding window keeps context manageable)
```

### Key Technical Features

- **Sliding Window**: เก็บแค่ 3 rounds ล่าสุดใน context ป้องกัน overflow
- **Auto-inject Notes**: `_notes.txt` ถูกโหลดเข้า context อัตโนมัติเมื่อ round เก่าถูกทิ้ง
- **Incremental Building**: AI สร้างงานทีละส่วน สะสมผ่านไฟล์
- **Truncation Handling**: output ใหญ่ถูก truncate + เตือนให้ AI save ก่อนหาย

## Customization

### เปลี่ยน Model

แก้ `Modelfile` บรรทัดแรก:
```
FROM ./your-model-file.gguf
```

แล้วรัน `start.bat` ใหม่ (จะ reload Modelfile อัตโนมัติ)

### เพิ่ม Context Window

แก้ `Modelfile`:
```
PARAMETER num_ctx 8192
```

> ยิ่ง context ใหญ่ยิ่งใช้ RAM มาก: 4096 = ~100MB, 8192 = ~200MB

### แก้ Config

แก้ตัวแปรด้านบนของ `app.py`:
```python
MAX_AGENT_LOOPS = 15      # จำนวน round สูงสุดต่อ task
MAX_AGENT_KEEP = 3        # sliding window size
MAX_MODEL_OUTPUT = 1500   # ขนาด output ที่ส่งกลับ model
```

## License

MIT - ใช้ได้อิสระ แก้ได้ แจกได้

## Credits

- Model: [Google Gemma](https://ai.google.dev/gemma)
- Uncensored variant: HauhauCS
- Runtime: [Ollama](https://ollama.com/)
- UI: [Gradio](https://gradio.app/)
