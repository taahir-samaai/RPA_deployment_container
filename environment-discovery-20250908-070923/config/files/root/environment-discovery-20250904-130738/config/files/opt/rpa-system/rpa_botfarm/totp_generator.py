#!/usr/bin/env python3
"""
TOTP PIN Generator Script
Generates Time-based One-Time Passwords using pyotp library
"""

import pyotp
import qrcode
import base64
import secrets
import argparse
from datetime import datetime

class TOTPGenerator:
    def __init__(self, secret=None):
        """
        Initialize TOTP generator with a secret key
        If no secret provided, generates a new one
        """
        if secret:
            self.secret = secret
        else:
            # Generate a random 32-character base32 secret
            self.secret = pyotp.random_base32()
        
        self.totp = pyotp.TOTP(self.secret)
    
    def generate_pin(self):
        """Generate current TOTP PIN"""
        return self.totp.now()
    
    def verify_pin(self, pin):
        """Verify a TOTP PIN (with 30-second window tolerance)"""
        return self.totp.verify(pin)
    
    def get_provisioning_uri(self, name, issuer="TOTPGenerator"):
        """Get provisioning URI for QR code generation"""
        return self.totp.provisioning_uri(name=name, issuer_name=issuer)
    
    def generate_qr_code(self, name, issuer="TOTPGenerator", filename="totp_qr.png"):
        """Generate QR code for easy setup in authenticator apps"""
        uri = self.get_provisioning_uri(name, issuer)
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(filename)
        return filename
    
    def get_remaining_time(self):
        """Get remaining time in seconds until next PIN"""
        import time
        return 30 - (int(time.time()) % 30)
    
    def continuous_display(self, interval=1):
        """Display TOTP PIN with countdown (Ctrl+C to stop)"""
        import time
        
        try:
            while True:
                pin = self.generate_pin()
                remaining = self.get_remaining_time()
                timestamp = datetime.now().strftime("%H:%M:%S")
                
                print(f"\r[{timestamp}] Current PIN: {pin} | Time left: {remaining:2d}s", end="", flush=True)
                
                if remaining == 30:  # New PIN generated
                    print()  # New line when PIN changes
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\nStopped.")

def main():
    parser = argparse.ArgumentParser(description="TOTP PIN Generator")
    parser.add_argument("-s", "--secret", help="Base32 secret key (generates new one if not provided)")
    parser.add_argument("-n", "--name", default="User", help="Account name for QR code")
    parser.add_argument("-i", "--issuer", default="TOTPGenerator", help="Issuer name for QR code")
    parser.add_argument("--qr", action="store_true", help="Generate QR code")
    parser.add_argument("--verify", help="Verify a TOTP PIN")
    parser.add_argument("--watch", action="store_true", help="Continuously display TOTP PIN")
    parser.add_argument("--show-secret", action="store_true", help="Display the secret key")
    
    args = parser.parse_args()
    
    # Initialize TOTP generator
    totp_gen = TOTPGenerator(args.secret)
    
    if args.show_secret:
        print(f"Secret Key: {totp_gen.secret}")
    
    if args.verify:
        is_valid = totp_gen.verify_pin(args.verify)
        print(f"PIN {args.verify} is {'VALID' if is_valid else 'INVALID'}")
        return
    
    if args.qr:
        filename = totp_gen.generate_qr_code(args.name, args.issuer)
        print(f"QR code saved as: {filename}")
        print(f"Provisioning URI: {totp_gen.get_provisioning_uri(args.name, args.issuer)}")
    
    if args.watch:
        print("Watching TOTP PIN (Press Ctrl+C to stop):")
        totp_gen.continuous_display()
    else:
        # Default: just show current PIN
        current_pin = totp_gen.generate_pin()
        remaining_time = totp_gen.get_remaining_time()
        print(f"Current TOTP PIN: {current_pin}")
        print(f"Valid for: {remaining_time} seconds")

if __name__ == "__main__":
    # Example usage without command line arguments
    if len(__import__('sys').argv) == 1:
        print("=== TOTP PIN Generator Demo ===")
        
        # Create new TOTP generator
        totp = TOTPGenerator()
        
        print(f"Generated Secret: {totp.secret}")
        print(f"Current PIN: {totp.generate_pin()}")
        print(f"Time remaining: {totp.get_remaining_time()} seconds")
        
        print("\nFor full functionality, run with --help to see all options")
        print("Example: python totp_generator.py --watch --show-secret")
    else:
        main()