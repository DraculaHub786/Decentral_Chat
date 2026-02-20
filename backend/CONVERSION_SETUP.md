# 📄 File Conversion Setup Guide

## 🎯 Overview

This guide will help you set up **complete file conversion** capabilities with **image and formatting preservation** for DecentralChat.

## 🔧 Current Issues (Before Setup)

- ❌ PDF → DOCX: Only text, **no images**
- ❌ PPT → PDF: Only text, **no slide layouts**
- ❌ DOCX → PDF: May fail or lose formatting
- ❌ All conversions: **Formatting lost**

## ✅ After Setup (Full Capability)

- ✅ PDF ↔ DOCX: **Full images, tables, formatting**
- ✅ PPT/PPTX → PDF: **All slides with images**
- ✅ Any Office format: **Professional quality**
- ✅ Media conversions: Audio/video processing

---

## 📦 Installation Steps

### Step 1: Install Python Dependencies

```bash
cd backend
pip install -r requirements-converter.txt
```

This installs:
- ✅ `pdf2docx` - PDF to DOCX with images
- ✅ `beautifulsoup4` - HTML parsing
- ✅ `markdown` - Markdown conversions
- ✅ Other document processing libraries

### Step 2: Install LibreOffice (⭐ CRITICAL for best quality)

LibreOffice is **FREE** and provides the best conversion quality.

#### Windows:
1. Download: https://www.libreoffice.org/download/download/
2. Run installer (LibreOffice_X.X.X_Win_x86-64.msi)
3. Install with default options
4. Verify: Open Command Prompt and run:
   ```cmd
   soffice --version
   ```
   Should show: `LibreOffice X.X.X.X`

#### macOS:
```bash
# Option 1: Download from website
# https://www.libreoffice.org/download/download/

# Option 2: Using Homebrew
brew install --cask libreoffice

# Verify
libreoffice --version
```

#### Linux (Ubuntu/Debian):
```bash
sudo apt-get update
sudo apt-get install libreoffice

# Verify
libreoffice --version
```

#### Linux (CentOS/RHEL):
```bash
sudo yum install libreoffice

# Verify
libreoffice --version
```

### Step 3: Install FFmpeg (For Audio/Video Conversions)

#### Windows:
1. Download: https://ffmpeg.org/download.html#build-windows
2. Extract to `C:\ffmpeg`
3. Add to PATH:
   - Search "Environment Variables" in Windows
   - Edit "Path" variable
   - Add `C:\ffmpeg\bin`
4. Restart terminal and verify:
   ```cmd
   ffmpeg -version
   ```

#### macOS:
```bash
brew install ffmpeg

# Verify
ffmpeg -version
```

#### Linux:
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# CentOS/RHEL
sudo yum install ffmpeg

# Verify
ffmpeg -version
```

---

## 🧪 Testing Your Setup

### Start the server:
```bash
cd backend
python server.py
```

### Look for these messages in the startup logs:

```
======================================================================
🔄 FILE CONVERSION CAPABILITIES
======================================================================
✅ pdf2docx: INSTALLED - High-quality PDF→DOCX with images
✅ LibreOffice: FOUND at /usr/bin/soffice
   Supports: PDF↔DOCX, PPT→PDF, with images & formatting
✅ BeautifulSoup4: INSTALLED - Enhanced HTML parsing
✅ Markdown: INSTALLED - Markdown conversions available
✅ FFmpeg: FOUND - Audio/video conversions available
======================================================================
✅ All conversion tools installed - Full capability available!
======================================================================
```

### Test conversions in the app:
1. Upload a PDF with images
2. Convert to DOCX
3. Check if images are preserved ✅
4. Upload a PowerPoint file
5. Convert to PDF
6. Check if slides look correct ✅

---

## 🎯 What Each Tool Provides

### pdf2docx (Python library)
- **PDF → DOCX** with images, tables, formatting
- Text extraction with positioning
- Best quality for PDF conversions

### LibreOffice (System tool) ⭐ MOST IMPORTANT
- **PDF ↔ DOCX** (both directions)
- **PPT/PPTX → PDF** (all slides)
- **DOCX → PDF** (with formatting)
- **Any Office format conversions**
- Preserves images, charts, tables
- Professional document rendering

### FFmpeg (System tool)
- Audio format conversions (MP3, WAV, AAC, etc.)
- Video format conversions (MP4, AVI, MKV, etc.)
- Video to audio extraction
- Codec transcoding

---

## 🐛 Troubleshooting

### Issue: "pdf2docx not installed" warning

**Solution:**
```bash
pip install pdf2docx
```

### Issue: "LibreOffice: NOT FOUND" warning

**Solution:**
- Install LibreOffice (see Step 2 above)
- Make sure `soffice` or `libreoffice` command works in terminal
- Windows: Verify the installation path is in system PATH

### Issue: "FFmpeg: NOT FOUND" warning

**Solution:**
- Install FFmpeg (see Step 3 above)
- Make sure `ffmpeg` command works in terminal
- Windows: Verify FFmpeg `bin` folder is in system PATH

### Issue: Conversions still text-only after installing LibreOffice

**Diagnosis Steps:**
1. Check LibreOffice is in PATH:
   ```bash
   # Windows
   where soffice
   
   # Mac/Linux
   which libreoffice
   ```

2. Test LibreOffice manually:
   ```bash
   soffice --headless --convert-to pdf test.docx
   ```

3. Restart your backend server after installing LibreOffice

### Issue: "docx2pdf library not installed" error

**Note:** This is **optional** and Windows-only. LibreOffice is better!

If you still want it:
```bash
pip install docx2pdf
```
Requires Microsoft Word installed.

---

## 📊 Conversion Quality Matrix

| From → To | Without Tools | With pdf2docx | With LibreOffice |
|-----------|--------------|---------------|------------------|
| PDF → DOCX | Text only ❌ | Images + text ✅ | Full quality ⭐ |
| PPT → PDF | Text only ❌ | Text only ❌ | All slides ⭐ |
| DOCX → PDF | May fail ❌ | Text only ⚠️ | Full quality ⭐ |
| Images | Basic ⚠️ | Basic ⚠️ | Basic ⚠️ |
| Media | Fails ❌ | Fails ❌ | + FFmpeg ⭐ |

**⭐ = Best quality with images, formatting, and structure preserved**

---

## 🚀 Recommended Setup (Best Quality)

For **professional-quality conversions**, install **all three**:

1. ✅ Python libraries (`requirements-converter.txt`)
2. ✅ **LibreOffice** (FREE, cross-platform)
3. ✅ **FFmpeg** (FREE, for media)

**Total time:** ~10 minutes
**Cost:** Free
**Result:** Enterprise-grade file conversion

---

## 💡 Quick Setup Script

### Windows (PowerShell):
```powershell
# Install Python dependencies
pip install -r requirements-converter.txt

# Download and install LibreOffice
Start-Process "https://www.libreoffice.org/download/download/"

# After installing LibreOffice, verify
soffice --version
```

### Linux (Ubuntu/Debian):
```bash
# One-line setup
pip install -r requirements-converter.txt && \
sudo apt-get install -y libreoffice ffmpeg && \
libreoffice --version && ffmpeg -version
```

### macOS:
```bash
# Using Homebrew
pip install -r requirements-converter.txt && \
brew install --cask libreoffice && \
brew install ffmpeg && \
libreoffice --version && ffmpeg -version
```

---

## ✅ Verification Checklist

After installation, you should have:

- [ ] Python dependencies installed (`pip list | grep pdf2docx`)
- [ ] LibreOffice installed (`soffice --version` works)
- [ ] FFmpeg installed (`ffmpeg -version` works)
- [ ] Server shows "All conversion tools installed"
- [ ] Test PDF→DOCX preserves images
- [ ] Test PPT→PDF shows all slides

---

## 📝 Notes

1. **LibreOffice is the key** - It provides the best quality for Office document conversions
2. **pdf2docx is essential** - For PDF parsing with images
3. **FFmpeg is optional** - Only needed for media file conversions
4. All tools are **FREE** and open-source
5. No external services or API keys required
6. Everything runs locally on your server

---

## 🆘 Need Help?

If you encounter issues:
1. Check the startup logs for specific errors
2. Verify each tool individually with the commands above
3. Restart the server after installing new tools
4. Check the console output during conversions

---

**With proper setup, your file converter will handle documents like a professional office suite!** 🎉
