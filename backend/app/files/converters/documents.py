from typing import Dict, Set, Optional, List
from aiohttp import web
import aiohttp_cors
from aiohttp_session import get_session
import asyncio, json, hashlib, jwt, datetime, uuid, os, base64, bcrypt, random, mimetypes, secrets, string, shutil, subprocess, tempfile, io
from datetime import timedelta
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth, storage as firebase_storage, firestore
import redis.asyncio as redis
from cryptography.fernet import Fernet
import logging
from pathlib import Path
from PIL import Image, ImageOps
import PyPDF2
from docx import Document
from pptx import Presentation
import openpyxl
from app.globals import g
from app.core.config import (REDIS_URL, SECRET_KEY, FIREBASE_CRED, PORT,
    MAX_FILE_SIZE, UPLOAD_DIR, ALLOWED_EXTENSIONS, ENCRYPTION_KEY,
    HAS_LIBREOFFICE, HAS_UNOCONV, FFMPEG_PATH, HAS_PDF2DOCX, PDFConverter,
    HAS_BS4, HAS_MARKDOWN, print_conversion_capabilities)
from app.core.security import (_ensure_secret_key, _ensure_fernet_key,
    _validate_password, _validate_file_magic, _resolve_safe_path, _log_safe, _is_admin)
from app.core.rate_limiter import RateLimiter
from app.core.redis_client import MockRedis, MockPipeline
from app.core.firebase_client import init_firebase
logger = logging.getLogger(__name__)
def convert_document_format(input_path, output_path, source_ext, target_ext):
    """Convert document formats - supports all major document types"""
    try:
        # Debug logging
        logger.info(f"🔍 Document conversion DEBUG - source_ext: '{source_ext}' (type: {type(source_ext)}), target_ext: '{target_ext}' (type: {type(target_ext)})")
        
        # PDF to text conversions
        if source_ext == 'pdf' and target_ext in ['txt', 'md', 'html', 'rtf']:
            text = ""
            with open(input_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n\n"
            
            if target_ext == 'html':
                text = f"<html><body><pre>{text}</pre></body></html>"
            elif target_ext == 'rtf':
                text = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times New Roman;}}\f0\fs24 " + text.replace('\n', r'\par ') + "}"
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return output_path
        
        # PDF to DOCX conversion (WITH IMAGES SUPPORT)
        elif source_ext == 'pdf' and target_ext == 'docx':
            conversion_successful = False
            
            # Method 1: Try pdf2docx (best quality, preserves images and formatting)
            if HAS_PDF2DOCX and PDFConverter:
                try:
                    logger.info("🔄 Method 1: Using pdf2docx for high-quality PDF→DOCX conversion (preserves images & formatting)")
                    cv = PDFConverter(input_path)
                    cv.convert(output_path, start=0, end=None)
                    cv.close()
                    
                    # Verify the output file was created and has content
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                        logger.info("✅ PDF to DOCX conversion successful with images preserved (pdf2docx)")
                        return output_path
                    else:
                        logger.warning("⚠️ pdf2docx created empty/invalid file, trying next method")
                        if os.path.exists(output_path):
                            os.remove(output_path)
                except Exception as pdf2docx_err:
                    logger.warning(f"⚠️ pdf2docx failed: {pdf2docx_err}, trying next method")
                    if os.path.exists(output_path):
                        try:
                            os.remove(output_path)
                        except:
                            pass
            
            # Method 2: Try LibreOffice (good quality, preserves some formatting)
            if not conversion_successful and HAS_LIBREOFFICE:
                try:
                    logger.info("🔄 Method 2: Using LibreOffice for PDF→DOCX conversion")
                    result = subprocess.run([
                        'soffice' if shutil.which('soffice') else 'libreoffice',
                        '--headless',
                        '--convert-to', 'docx',
                        '--outdir', os.path.dirname(output_path),
                        input_path
                    ], capture_output=True, text=True, timeout=120)
                    
                    # LibreOffice creates file with original name + .docx
                    expected_output = os.path.join(
                        os.path.dirname(output_path),
                        os.path.splitext(os.path.basename(input_path))[0] + '.docx'
                    )
                    
                    if os.path.exists(expected_output):
                        if expected_output != output_path:
                            shutil.move(expected_output, output_path)
                        logger.info("✅ PDF to DOCX conversion successful (LibreOffice)")
                        return output_path
                    else:
                        logger.warning(f"⚠️ LibreOffice conversion failed: {result.stderr}")
                except subprocess.TimeoutExpired:
                    logger.warning("⚠️ LibreOffice conversion timed out")
                except Exception as libre_err:
                    logger.warning(f"⚠️ LibreOffice conversion failed: {libre_err}")
            
            # Method 3: Fallback to text-only extraction with PyPDF2
            logger.info("🔄 Method 3: Using PyPDF2 for text-only PDF→DOCX conversion (WARNING: No images)")
            try:
                doc = Document()
                with open(input_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    for i, page in enumerate(pdf_reader.pages):
                        text = page.extract_text()
                        if text.strip():
                            if i == 0:
                                doc.add_paragraph(text)
                            else:
                                doc.add_page_break()
                                doc.add_paragraph(text)
                doc.save(output_path)
                logger.info("✅ PDF to DOCX conversion successful (text-only)")
                return output_path
            except Exception as pdf_docx_err:
                logger.error(f"❌ PDF to DOCX conversion error: {pdf_docx_err}")
                raise Exception(f"PDF to DOCX conversion failed: {str(pdf_docx_err)}")
        
        # DOCX conversions
        elif source_ext in ['docx', 'doc'] and target_ext in ['txt', 'md', 'html', 'rtf']:
            doc = Document(input_path)
            text = '\n\n'.join([p.text for p in doc.paragraphs if p.text.strip()])
            
            if target_ext == 'html':
                html_text = '<html><body>'
                for p in doc.paragraphs:
                    if p.text.strip():
                        html_text += f'<p>{p.text}</p>'
                html_text += '</body></html>'
                text = html_text
            elif target_ext == 'rtf':
                text = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times New Roman;}}\f0\fs24 " + text.replace('\n', r'\par ') + "}"
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return output_path
        
        elif source_ext == 'docx' and target_ext == 'pdf':
            # Method 1: Try LibreOffice (best quality, preserves images)
            if HAS_LIBREOFFICE:
                try:
                    logger.info("🔄 Using LibreOffice for DOCX→PDF conversion (preserves images)")
                    result = subprocess.run([
                        'soffice' if shutil.which('soffice') else 'libreoffice',
                        '--headless',
                        '--convert-to', 'pdf',
                        '--outdir', os.path.dirname(output_path),
                        input_path
                    ], capture_output=True, text=True, timeout=120)
                    
                    expected_output = os.path.join(
                        os.path.dirname(output_path),
                        os.path.splitext(os.path.basename(input_path))[0] + '.pdf'
                    )
                    
                    if os.path.exists(expected_output):
                        if expected_output != output_path:
                            shutil.move(expected_output, output_path)
                        logger.info("✅ DOCX to PDF conversion successful (LibreOffice)")
                        return output_path
                except Exception as libre_err:
                    logger.warning(f"⚠️ LibreOffice DOCX→PDF failed: {libre_err}, trying docx2pdf")
            
            # Method 2: Try docx2pdf (Windows only, may not preserve all images)
            try:
                logger.info("🔄 Using docx2pdf for DOCX→PDF conversion")
                from docx2pdf import convert as docx_to_pdf
                docx_to_pdf(input_path, output_path)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    logger.info("✅ DOCX to PDF conversion successful (docx2pdf)")
                    return output_path
            except ImportError:
                logger.error("❌ docx2pdf not available and LibreOffice failed")
                raise Exception("PDF conversion requires either LibreOffice or docx2pdf. Install LibreOffice for better results.")
            except Exception as docx2pdf_err:
                logger.error(f"❌ docx2pdf conversion failed: {docx2pdf_err}")
                raise Exception(f"DOCX to PDF conversion failed: {docx2pdf_err}")
        
        # Text to document conversions
        elif source_ext == 'txt' and target_ext in ['html', 'md', 'rtf']:
            with open(input_path, 'r', encoding='utf-8') as f:
                text = f.read()
            
            if target_ext == 'html':
                text = f"<html><body><pre>{text}</pre></body></html>"
            elif target_ext == 'rtf':
                text = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times New Roman;}}\f0\fs24 " + text.replace('\n', r'\par ') + "}"
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return output_path
        
        elif source_ext == 'txt' and target_ext == 'docx':
            doc = Document()
            with open(input_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        doc.add_paragraph(line.strip())
            doc.save(output_path)
            return output_path
        
        elif source_ext == 'txt' and target_ext == 'pdf':
            # Convert TXT to PDF via DOCX
            try:
                from docx2pdf import convert as docx_to_pdf
                # Create temp DOCX
                temp_docx = output_path + '.temp.docx'
                doc = Document()
                with open(input_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            doc.add_paragraph(line.strip())
                doc.save(temp_docx)
                # Convert to PDF
                docx_to_pdf(temp_docx, output_path)
                # Clean up temp file
                try:
                    os.remove(temp_docx)
                except:
                    pass
                return output_path
            except ImportError:
                raise Exception("docx2pdf library not installed. Run: pip install docx2pdf")
        
        # HTML to text conversions
        elif source_ext == 'html' and target_ext in ['txt', 'md', 'docx', 'pdf']:
            with open(input_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # Parse HTML and extract text using BeautifulSoup if available
            if HAS_BS4:
                logger.info("🔄 Using BeautifulSoup for HTML parsing")
                soup = BeautifulSoup(html_content, 'html.parser')
                text = soup.get_text(separator='\\n')
            else:
                # Basic HTML tag removal
                logger.info("🔄 Using basic regex for HTML parsing")
                import re
                text = re.sub('<[^<]+?>', '', html_content)
            
            if not text.strip():
                raise Exception("No text content found in HTML")
            
            if target_ext == 'docx':
                doc = Document()
                for line in text.split('\n'):
                    if line.strip():
                        doc.add_paragraph(line.strip())
                doc.save(output_path)
                return output_path
            elif target_ext == 'pdf':
                # Convert HTML to PDF via DOCX
                try:
                    from docx2pdf import convert as docx_to_pdf
                    temp_docx = output_path + '.temp.docx'
                    doc = Document()
                    for line in text.split('\n'):
                        if line.strip():
                            doc.add_paragraph(line.strip())
                    doc.save(temp_docx)
                    docx_to_pdf(temp_docx, output_path)
                    try:
                        os.remove(temp_docx)
                    except:
                        pass
                    logger.info("✅ HTML to PDF conversion successful")
                except ImportError:
                    raise Exception("docx2pdf library not installed")
            else:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                logger.info(f"✅ HTML to {target_ext.upper()} conversion successful")
            return output_path
        
        # Markdown conversions
        elif source_ext == 'md' and target_ext in ['txt', 'html', 'docx', 'pdf']:
            with open(input_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            
            if not md_content.strip():
                raise Exception("Source markdown file is empty")
            
            if target_ext == 'html':
                if HAS_MARKDOWN:
                    logger.info("🔄 Using markdown library for MD→HTML conversion")
                    html_body = markdown.markdown(md_content, extensions=['extra', 'codehilite'])
                    html = f"<html><head><meta charset='utf-8'></head><body>{html_body}</body></html>"
                else:
                    logger.info("🔄 Using basic HTML wrapping for MD→HTML conversion")
                    html = f"<html><head><meta charset='utf-8'></head><body><pre>{md_content}</pre></body></html>"
                text = html
            elif target_ext == 'docx':
                doc = Document()
                for line in md_content.split('\n'):
                    if line.strip():
                        doc.add_paragraph(line.strip())
                doc.save(output_path)
                return output_path
            elif target_ext == 'pdf':
                # Convert MD to PDF via DOCX
                try:
                    from docx2pdf import convert as docx_to_pdf
                    temp_docx = output_path + '.temp.docx'
                    doc = Document()
                    for line in md_content.split('\n'):
                        if line.strip():
                            doc.add_paragraph(line.strip())
                    doc.save(temp_docx)
                    docx_to_pdf(temp_docx, output_path)
                    try:
                        os.remove(temp_docx)
                    except:
                        pass
                    return output_path
                except ImportError:
                    raise Exception("docx2pdf library not installed")
            else:
                text = md_content
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return output_path
        
        # Excel/CSV conversions
        elif source_ext in ['xlsx', 'xls'] and target_ext == 'csv':
            wb = openpyxl.load_workbook(input_path)
            sheet = wb.active
            with open(output_path, 'w', encoding='utf-8', newline='') as f:
                import csv
                writer = csv.writer(f)
                for row in sheet.iter_rows(values_only=True):
                    writer.writerow(row)
            return output_path
        
        elif source_ext == 'csv' and target_ext in ['xlsx', 'txt']:
            if target_ext == 'xlsx':
                wb = openpyxl.Workbook()
                sheet = wb.active
                with open(input_path, 'r', encoding='utf-8') as f:
                    import csv
                    reader = csv.reader(f)
                    for row in reader:
                        sheet.append(row)
                wb.save(output_path)
            else:
                # CSV to TXT
                with open(input_path, 'r', encoding='utf-8') as fin:
                    with open(output_path, 'w', encoding='utf-8') as fout:
                        fout.write(fin.read())
            return output_path
        
        # PowerPoint conversions (IMPROVED - preserves images and formatting)
        elif source_ext in ['pptx', 'ppt'] and target_ext in ['txt', 'pdf', 'html', 'docx']:
            conversion_successful = False
            
            # Method 1: Use LibreOffice for PDF conversion (preserves images and formatting)
            if target_ext == 'pdf' and HAS_LIBREOFFICE:
                try:
                    logger.info("🔄 Method 1: Using LibreOffice for PPT→PDF conversion (preserves images & formatting)")
                    result = subprocess.run([
                        'soffice' if shutil.which('soffice') else 'libreoffice',
                        '--headless',
                        '--convert-to', 'pdf',
                        '--outdir', os.path.dirname(output_path),
                        input_path
                    ], capture_output=True, text=True, timeout=120)
                    
                    expected_output = os.path.join(
                        os.path.dirname(output_path),
                        os.path.splitext(os.path.basename(input_path))[0] + '.pdf'
                    )
                    
                    if os.path.exists(expected_output):
                        if expected_output != output_path:
                            shutil.move(expected_output, output_path)
                        logger.info("✅ PPT to PDF conversion successful with images preserved (LibreOffice)")
                        return output_path
                    else:
                        logger.warning(f"⚠️ LibreOffice PPT conversion failed: {result.stderr}")
                except Exception as libre_err:
                    logger.warning(f"⚠️ LibreOffice PPT conversion error: {libre_err}")
            
            # Method 2: Use LibreOffice for DOCX conversion
            if target_ext == 'docx' and HAS_LIBREOFFICE:
                try:
                    logger.info("🔄 Using LibreOffice for PPT→DOCX conversion (preserves formatting)")
                    result = subprocess.run([
                        'soffice' if shutil.which('soffice') else 'libreoffice',
                        '--headless',
                        '--convert-to', 'docx',
                        '--outdir', os.path.dirname(output_path),
                        input_path
                    ], capture_output=True, text=True, timeout=120)
                    
                    expected_output = os.path.join(
                        os.path.dirname(output_path),
                        os.path.splitext(os.path.basename(input_path))[0] + '.docx'
                    )
                    
                    if os.path.exists(expected_output):
                        if expected_output != output_path:
                            shutil.move(expected_output, output_path)
                        logger.info("✅ PPT to DOCX conversion successful (LibreOffice)")
                        return output_path
                except Exception as libre_err:
                    logger.warning(f"⚠️ LibreOffice conversion error: {libre_err}")
            
            # Method 3: Fallback to text-only extraction
            logger.info("🔄 Fallback: Text-only PPT conversion (WARNING: No images or formatting)")
            prs = Presentation(input_path)
            text = []
            for slide_num, slide in enumerate(prs.slides, 1):
                text.append(f"\n=== Slide {slide_num} ===")
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        text.append(shape.text)
            text_content = '\n\n'.join(text)
            
            if target_ext == 'txt':
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text_content)
                return output_path
            elif target_ext == 'html':
                html = f"<html><head><meta charset='utf-8'></head><body><pre>{text_content}</pre></body></html>"
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(html)
                return output_path
            elif target_ext == 'docx':
                doc = Document()
                for slide_num, slide in enumerate(prs.slides, 1):
                    if slide_num > 1:
                        doc.add_page_break()
                    doc.add_heading(f'Slide {slide_num}', level=1)
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            doc.add_paragraph(shape.text)
                doc.save(output_path)
                return output_path
            elif target_ext == 'pdf':
                # Last resort: text-only PDF
                try:
                    from docx2pdf import convert as docx_to_pdf
                    temp_docx = output_path + '.temp.docx'
                    doc = Document()
                    for slide_num, slide in enumerate(prs.slides, 1):
                        if slide_num > 1:
                            doc.add_page_break()
                        doc.add_heading(f'Slide {slide_num}', level=1)
                        for shape in slide.shapes:
                            if hasattr(shape, "text") and shape.text.strip():
                                doc.add_paragraph(shape.text)
                    doc.save(temp_docx)
                    docx_to_pdf(temp_docx, output_path)
                    try:
                        os.remove(temp_docx)
                    except:
                        pass
                    logger.info("✅ PPT to PDF conversion complete (text-only)")
                    return output_path
                except ImportError:
                    raise Exception("docx2pdf library not installed and LibreOffice not available. Install LibreOffice for better conversion.")
        
        # RTF conversions
        elif source_ext == 'rtf' and target_ext in ['txt', 'docx', 'pdf', 'html']:
            # Basic RTF to text extraction (remove RTF codes)
            with open(input_path, 'r', encoding='utf-8') as f:
                rtf_content = f.read()
            import re
            text = re.sub(r'\\[a-z]+\d*\s?', '', rtf_content)
            text = re.sub(r'[{}]', '', text)
            
            if target_ext == 'txt':
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(text)
            elif target_ext == 'docx':
                doc = Document()
                for line in text.split('\n'):
                    if line.strip():
                        doc.add_paragraph(line.strip())
                doc.save(output_path)
            elif target_ext == 'html':
                html = f"<html><body><pre>{text}</pre></body></html>"
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(html)
            elif target_ext == 'pdf':
                try:
                    from docx2pdf import convert as docx_to_pdf
                    temp_docx = output_path + '.temp.docx'
                    doc = Document()
                    for line in text.split('\n'):
                        if line.strip():
                            doc.add_paragraph(line.strip())
                    doc.save(temp_docx)
                    docx_to_pdf(temp_docx, output_path)
                    try:
                        os.remove(temp_docx)
                    except:
                        pass
                except ImportError:
                    raise Exception("docx2pdf library not installed")
            return output_path
        
        # Excel conversions
        elif source_ext in ['xlsx', 'xls'] and target_ext in ['csv', 'txt', 'html', 'pdf']:
            wb = openpyxl.load_workbook(input_path)
            sheet = wb.active
            
            if target_ext == 'csv':
                with open(output_path, 'w', encoding='utf-8', newline='') as f:
                    import csv
                    writer = csv.writer(f)
                    for row in sheet.iter_rows(values_only=True):
                        writer.writerow(row)
            elif target_ext == 'txt':
                with open(output_path, 'w', encoding='utf-8') as f:
                    for row in sheet.iter_rows(values_only=True):
                        f.write('\t'.join([str(cell) if cell else '' for cell in row]) + '\n')
            elif target_ext == 'html':
                html = '<html><body><table border="1">'
                for row in sheet.iter_rows(values_only=True):
                    html += '<tr>'
                    for cell in row:
                        html += f'<td>{cell if cell else ""}</td>'
                    html += '</tr>'
                html += '</table></body></html>'
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(html)
            elif target_ext == 'pdf':
                # Convert Excel to PDF via text
                try:
                    from docx2pdf import convert as docx_to_pdf
                    temp_docx = output_path + '.temp.docx'
                    doc = Document()
                    for row in sheet.iter_rows(values_only=True):
                        line = '\t'.join([str(cell) if cell else '' for cell in row])
                        if line.strip():
                            doc.add_paragraph(line)
                    doc.save(temp_docx)
                    docx_to_pdf(temp_docx, output_path)
                    try:
                        os.remove(temp_docx)
                    except:
                        pass
                except ImportError:
                    raise Exception("docx2pdf library not installed")
            return output_path
        
        elif source_ext == 'csv' and target_ext in ['xlsx', 'txt', 'html', 'pdf']:
            if target_ext == 'xlsx':
                wb = openpyxl.Workbook()
                sheet = wb.active
                with open(input_path, 'r', encoding='utf-8') as f:
                    import csv
                    reader = csv.reader(f)
                    for row in reader:
                        sheet.append(row)
                wb.save(output_path)
            elif target_ext in ['txt', 'html', 'pdf']:
                with open(input_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if target_ext == 'txt':
                    with open(output_path, 'w', encoding='utf-8') as fout:
                        fout.write(content)
                elif target_ext == 'html':
                    html = f"<html><body><pre>{content}</pre></body></html>"
                    with open(output_path, 'w', encoding='utf-8') as fout:
                        fout.write(html)
                elif target_ext == 'pdf':
                    try:
                        from docx2pdf import convert as docx_to_pdf
                        temp_docx = output_path + '.temp.docx'
                        doc = Document()
                        doc.add_paragraph(content)
                        doc.save(temp_docx)
                        docx_to_pdf(temp_docx, output_path)
                        try:
                            os.remove(temp_docx)
                        except:
                            pass
                    except ImportError:
                        raise Exception("docx2pdf library not installed")
            return output_path
        
        # Unsupported conversion
        logger.error(f"❌ Unsupported document conversion: {source_ext} → {target_ext}")
        raise Exception(f"Document conversion {source_ext} → {target_ext} not implemented")
        
    except Exception as e:
        if "not implemented" in str(e) or "not installed" in str(e):
            raise
        logger.error(f"❌ Document conversion failed: {str(e)}")
        raise Exception(f"Document conversion failed: {str(e)}")

