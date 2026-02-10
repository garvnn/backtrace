"""
Base strategy class.
"""

from abc import ABC, abstractmethod

class Strategy(ABC):
    def __init__(self, name="BaseStrategy"):
        self.name = name
    
    @abstractmethod
    def generate_signals(self, data):
        """
        Generate trading signals.
        
        Args:
            data: DataFrame with price data
            
        Returns:
            Series with 1 (long), 0 (flat), -1 (short)
        """
        pass