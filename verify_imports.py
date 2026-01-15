#!/usr/bin/env python
"""
Quick script to verify all imports work correctly
"""
import sys

try:
    from rest_framework import serializers
    print("✓ rest_framework imported successfully")
except ImportError as e:
    print(f"✗ rest_framework import failed: {e}")
    print("\nTo fix: pip install djangorestframework")
    sys.exit(1)

try:
    from django.contrib.auth.models import User
    print("✓ Django models imported successfully")
except ImportError as e:
    print(f"✗ Django import failed: {e}")
    print("\nTo fix: pip install Django")
    sys.exit(1)

try:
    from core.models import Airport
    print("✓ Core models imported successfully")
except ImportError as e:
    print(f"✗ Core models import failed: {e}")
    print("\nMake sure you're running from the project root and Django is set up")
    sys.exit(1)

print("\n✓ All imports verified successfully!")
