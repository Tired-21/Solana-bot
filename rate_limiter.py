"""
rate_limiter.py - API Rate Limiting
"""

import time
from config import RATE_LIMITS, DEBUG_MODE


class RateLimiter:
    def __init__(self):
        self.last_call = {}
    
    def wait(self, api_name):
        rate = RATE_LIMITS.get(api_name, 1.0)
        min_interval = 1.0 / rate
        
        last = self.last_call.get(api_name, 0)
        now = time.time()
        elapsed = now - last
        
        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            if DEBUG_MODE:
                print(f"⏳ Rate limit: waiting {wait_time:.2f}s for {api_name}")
            time.sleep(wait_time)
        
        self.last_call[api_name] = time.time()
    
    def reset(self, api_name=None):
        if api_name:
            self.last_call.pop(api_name, None)
        else:
            self.last_call = {}


# Global instance shared across all modules
rate_limiter = RateLimiter()


def wait_for(api_name):
    """Convenience function."""
    rate_limiter.wait(api_name)


if __name__ == "__main__":
    print("Testing rate_limiter.py...")
    print("Making 3 rapid calls to 'dexscreener':")
    
    for i in range(3):
        wait_for("dexscreener")
        print(f"  Call {i+1} at {time.strftime('%H:%M:%S')}")
    
    print("✅ rate_limiter.py working!")