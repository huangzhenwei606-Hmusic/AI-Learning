students = [
    {
        "student": "Emma",
        "today": "C major scale",
        "performance": "focused and followed instructions well",
        "improvement": "needs more finger control and evenness when moving between notes",
        "homework": "practice the C major scale for 10 minutes daily, slowly and carefully",
        "next_goal": "play the scale with steady rhythm and relaxed hands"
    },

    {
        "student": "Tom",
        "today": "reading quarter notes",
        "performance": "very energetic and engaged during class",
        "improvement": "needs to slow down and count more carefully",
        "homework": "practice clapping rhythms for 5 minutes daily",
        "next_goal": "play simple rhythm exercises steadily"
    }
]

for s in students:

    feedback = f"""
====================================

Today {s["student"]} worked on {s["today"]}.

{s["student"]} was {s["performance"]}. 
The main area to improve is that {s["improvement"]}.

For home practice, please have {s["student"]} {s["homework"]}.

Next goal:
{s["next_goal"]}.

Overall, {s["student"]} is making steady progress. Great job!

====================================
"""

    print(feedback)