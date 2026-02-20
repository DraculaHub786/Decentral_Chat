#!/usr/bin/env python3
"""
File Converter Test Suite
Tests all conversion types to ensure production-ready quality
"""

import os
import sys
from pathlib import Path
from PIL import Image
from docx import Document
import io

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def create_test_files():
    """Create test files for conversion testing"""
    test_dir = Path('./test_conversions')
    test_dir.mkdir(exist_ok=True)
    
    print("📁 Creating test files...")
    
    # 1. Create test image (JPG)
    img = Image.new('RGB', (800, 600), color=(73, 109, 137))
    img.save(test_dir / 'test_image.jpg', 'JPEG')
    print("✅ Created test_image.jpg")
    
    # 2. Create test document (TXT)
    with open(test_dir / 'test_document.txt', 'w', encoding='utf-8') as f:
        f.write("This is a test document.\\nIt has multiple lines.\\nFor conversion testing.")
    print("✅ Created test_document.txt")
    
    # 3. Create test DOCX
    doc = Document()
    doc.add_heading('Test Document', 0)
    doc.add_paragraph('This is a test paragraph for conversion.')
    doc.save(test_dir / 'test_document.docx')
    print("✅ Created test_document.docx")
    
    # 4. Create test HTML
    with open(test_dir / 'test_page.html', 'w', encoding='utf-8') as f:
        f.write("""<html>
<head><title>Test Page</title></head>
<body>
    <h1>Test Heading</h1>
    <p>This is a test paragraph.</p>
</body>
</html>""")
    print("✅ Created test_page.html")
    
    return test_dir

def test_image_conversions(server):
    """Test image format conversions"""
    print("\\n🖼️ TESTING IMAGE CONVERSIONS")
    print("=" * 50)
    
    test_dir = Path('./test_conversions')
    input_file = test_dir / 'test_image.jpg'
    
    conversions = [
        ('png', 'PNG format'),
        ('webp', 'WebP format'),
        ('ico', 'ICO format (multi-resolution)'),
        ('bmp', 'BMP format'),
        ('gif', 'GIF format'),
    ]
    
    for target_ext, desc in conversions:
        try:
            output_file = test_dir / f'test_image.{target_ext}'
            server.convert_image_format(str(input_file), str(output_file), target_ext)
            
            if output_file.exists():
                size = output_file.stat().st_size
                print(f"  ✅ JPG → {target_ext.upper()}: {desc} ({size:,} bytes)")
            else:
                print(f"  ❌ JPG → {target_ext.upper()}: Failed - file not created")
        except Exception as e:
            print(f"  ❌ JPG → {target_ext.upper()}: {str(e)}")

def test_document_conversions(server):
    """Test document format conversions"""
    print("\\n📄 TESTING DOCUMENT CONVERSIONS")
    print("=" * 50)
    
    test_dir = Path('./test_conversions')
    
    # Test TXT conversions
    conversions = [
        (test_dir / 'test_document.txt', 'txt', 'docx', 'TXT → DOCX'),
        (test_dir / 'test_document.txt', 'txt', 'html', 'TXT → HTML'),
        (test_dir / 'test_document.docx', 'docx', 'txt', 'DOCX → TXT'),
        (test_dir / 'test_document.docx', 'docx', 'html', 'DOCX → HTML'),
        (test_dir / 'test_page.html', 'html', 'txt', 'HTML → TXT'),
    ]
    
    for input_file, source_ext, target_ext, desc in conversions:
        try:
            output_file = test_dir / f'{input_file.stem}_converted.{target_ext}'
            server.convert_document_format(
                str(input_file), 
                str(output_file), 
                source_ext, 
                target_ext
            )
            
            if output_file.exists():
                size = output_file.stat().st_size
                print(f"  ✅ {desc}: Success ({size:,} bytes)")
            else:
                print(f"  ❌ {desc}: Failed - file not created")
        except Exception as e:
            print(f"  ⚠️ {desc}: {str(e)}")

def main():
    """Run all conversion tests"""
    print("\\n" + "=" * 70)
    print("🔧 FILE CONVERTER PRODUCTION TEST SUITE")
    print("=" * 70)
    
    # Import server class
    try:
        from server import DecentralChatServer
        server = DecentralChatServer()
        print("✅ Server class loaded successfully\\n")
    except Exception as e:
        print(f"❌ Failed to load server: {e}")
        return
    
    # Create test files
    test_dir = create_test_files()
    
    # Run tests
    test_image_conversions(server)
    test_document_conversions(server)
    
    # Summary
    print("\\n" + "=" * 70)
    print("📊 TEST SUMMARY")
    print("=" * 70)
    print(f"✅ Test files created in: {test_dir.absolute()}")
    print("🔍 Check the test_conversions folder to verify outputs")
    print("\\n⚠️ Note: Some conversions may require additional software:")
    print("   - DOCX to PDF: Requires Microsoft Word or LibreOffice")
    print("   - Audio/Video: Requires FFmpeg in PATH")
    print("=" * 70)

if __name__ == '__main__':
    main()
