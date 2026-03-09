# predictor.py
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
import numpy as np

# Simulated pre-trained model
model = LogisticRegression(multi_class='multinomial', solver='lbfgs')
le = LabelEncoder()

# Dummy training setup
sample_outcomes = ["Win1", "Draw", "Win2"]
le.fit(sample_outcomes)
model.classes_ = le.classes_
model.coef_ = np.array([[0.8, -0.1, -0.7]])  # dummy weights
model.intercept_ = np.array([0.1])

def predict_match(delta_strength):
    """
    Predict probabilities of Win1, Draw, Win2 based on strength difference.
    """
    probas = model.predict_proba([[delta_strength]])[0]
    return dict(zip(le.inverse_transform([0, 1, 2]), probas))

def get_double_chances(probs):
    """
    Calculate double chance probabilities (1x and x2).
    """
    win1 = probs["Win1"]
    draw = probs["Draw"]
    win2 = probs["Win2"]
    return {
        "1x": win1 + draw,
        "x2": draw + win2
    }