import json

with open("lesson_history.json", "r") as file:
    for line in file:
        lesson = json.loads(line)

        print("Student:", lesson["student"])
        print("Lesson:", lesson["lesson"])
        print("Performance:", lesson["performance"])
        print("Homework:", lesson["homework"])
        print("---------")