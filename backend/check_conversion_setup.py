#!/usr/bin/env python3
"""
File Conversion Diagnostic Tool
Checks if all required tools are installed and working correctly
"""

import sys
import subprocess
import shutil
from pathlib import Path

def print_section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def check_python_package(package_name, import_name=None):
    """Check if a Python package is installed"""
    if import_name is None:
        import_name = package_name.replace('-', '_')
    
    try:
        __import__(import_name)
        print(f"✅ {package_name}: INSTALLED")
        return True
    except ImportError:
        print(f"❌ {package_name}: NOT INSTALLED")
        print(f"   Install with: pip install {package_name}")
        return False

def check_system_tool(command, name):
    """Check if a system tool is installed"""
    tool_path = shutil.which(command)
    if tool_path:
        print(f"✅ {name}: FOUND at {tool_path}")
        
        # Try to get version
        try:
            result = subprocess.run([command, '--version'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=5)
            version_output = result.stdout.split('\n')[0] if result.stdout else result.stderr.split('\n')[0]
            print(f"   Version: {version_output.strip()}")
        except:
            pass
        
        return True
    else:
        print(f"❌ {name}: NOT FOUND")
        return False

def main():
    print("\n" + "🔍" * 35)
    print("    DecentralChat File Conversion Diagnostic Tool")
    print("🔍" * 35)
    
    all_ok = True
    
    # Check Python packages
    print_section("Python Packages")
    packages = [
        ('Pillow', 'PIL'),
        ('PyPDF2', 'PyPDF2'),
        ('pdf2docx', 'pdf2docx'),
        ('python-docx', 'docx'),
        ('python-pptx', 'pptx'),
        ('openpyxl', 'openpyxl'),
        ('beautifulsoup4', 'bs4'),
        ('markdown', 'markdown'),
    ]
    
    for pkg_name, import_name in packages:
        if not check_python_package(pkg_name, import_name):
            all_ok = False
    
    # Check optional package
    print("\n📦 Optional (Windows only):")
    check_python_package('docx2pdf', 'docx2pdf')
    
    # Check system tools
    print_section("System Tools")
    
    # Check LibreOffice
    libreoffice_found = False
    for cmd in ['soffice', 'libreoffice']:
        if check_system_tool(cmd, f'LibreOffice ({cmd})'):
            libreoffice_found = True
            break
    
    if not libreoffice_found:
        print("⚠️  LibreOffice NOT FOUND - This is CRITICAL for best conversion quality")
        print("   Install from: https://www.libreoffice.org/download/")
        all_ok = False
    
    # Check FFmpeg
    print()
    if not check_system_tool('ffmpeg', 'FFmpeg'):
        print("⚠️  FFmpeg NOT FOUND - Required for audio/video conversions")
        print("   Install from: https://ffmpeg.org/download.html")
    
    # Summary
    print_section("Summary")
    
    if all_ok and libreoffice_found:
        print("🎉 ✅ ALL REQUIRED TOOLS INSTALLED!")
        print("   Your file converter is ready for production use.")
        print("   All conversions will preserve images and formatting.")
    else:
        print("⚠️  SETUP INCOMPLETE")
        print("\nMissing components:")
        if not all_ok:
            print("   • Some Python packages (see above)")
        if not libreoffice_found:
            print("   • LibreOffice (CRITICAL - install this first!)")
        print("\n📖 See CONVERSION_SETUP.md for detailed installation instructions")
    
    # Capabilities
    print_section("Expected Conversion Capabilities")
    
    if all_ok and libreoffice_found:
        print("✅ PDF → DOCX: Full quality with images")
        print("✅ PPT → PDF: All slides with formatting")
        print("✅ DOCX → PDF: Professional quality")
        print("✅ All Office formats: Best quality")
    else:
        print("⚠️  PDF → DOCX: Text only (no images)")
        print("⚠️  PPT → PDF: Text only (no slides)")
        print("⚠️  DOCX → PDF: May fail or low quality")
    
    print("\n" + "=" * 70)
    print("Run this script again after installing missing tools")
    print("=" * 70 + "\n")
    
    return 0 if (all_ok and libreoffice_found) else 1

if __name__ == "__main__":
    sys.exit(main())
