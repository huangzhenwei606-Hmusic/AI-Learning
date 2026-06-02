import json

student_name = input("Student Name: ")

excellent = 0
good = 0
fair = 0

with open("lesson_history.json", "r") as file:

    for line in file:

        lesson = json.loads(line)

        if lesson["student"].lower() == student_name.lower():

            if lesson["performance"].lower() == "excellent":
                excellent += 1

            elif lesson["performance"].lower() == "good":
                good += 1

            elif lesson["performance"].lower() == "fair":
                fair += 1

print("\nPerformance Report\n")

print("Excellent:", excellent)
print("Good:", good)
print("Fair:", fair)