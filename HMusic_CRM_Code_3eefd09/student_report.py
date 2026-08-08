import json

student_name = input("Student Name: ")

print("\nHistory:\n")

with open("lesson_history.json", "r") as file:
    for line in file:
        lesson = json.loads(line)

        if lesson["student"].lower() == student_name.lower():

            print("Lesson:", lesson["lesson"])
            print("Performance:", lesson["performance"])
            print("Homework:", lesson["homework"])
            print("--------")