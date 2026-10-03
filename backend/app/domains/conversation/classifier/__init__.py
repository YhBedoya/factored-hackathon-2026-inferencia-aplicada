"""Learned intent classifier: scorers shared by training and serving (REQ-learned-intent-fallback).

sklearn and fastembed are imported lazily inside the scorers, so importing this
package never needs the ``ml`` dependency group.
"""

from app.domains.conversation.classifier.adapter import ClassifierAdapter, IntentClassifier
from app.domains.conversation.classifier.loader import load_classifier
from app.domains.conversation.classifier.scorers import Scorer

__all__ = ["ClassifierAdapter", "IntentClassifier", "Scorer", "load_classifier"]
