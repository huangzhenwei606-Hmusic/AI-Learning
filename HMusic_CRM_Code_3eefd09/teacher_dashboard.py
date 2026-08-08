import json

teacher_name = input("Teacher Name: ")

total_lessons = 0
excellent = 0
good = 0
fair = 0

with open("lesson_history.json", "r") as file:

    for line in file:

        lesson = json.loads(line)

        if lesson.get("teacher", "").lower() == teacher_name.lower():

            total_lessons += 1

            if lesson["performance"].lower() == "excellent":
                excellent += 1

            elif lesson["performance"].lower() == "good":
                good += 1

            elif lesson["performance"].lower() == "fair":
                fair += 1

print("\nTeacher Dashboard")
print("------------------")

print("Teacher:", teacher_name)
print("Total Lessons:", total_lessons)

print("\nPerformance Summary")

print("Excellent:", excellent)
print("Good:", good)
print("Fair:", fair)