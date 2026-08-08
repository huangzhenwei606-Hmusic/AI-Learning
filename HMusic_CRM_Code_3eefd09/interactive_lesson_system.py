students = {
    "Emma": 10,
    "Tom": 8,
    "Sophia": 2
}


def deduct_lesson(student):

    if student not in students:

        print("Student not found.")
        return

    students[student] -= 1

    print(f"{student} finished a lesson.")

    print(f"Remaining lessons: {students[student]}")

    if students[student] <= 2:

        print("⚠️ Contact parent for renewal.")

    print("---------")


student_name = input("Which student finished lesson? ")

deduct_lesson(student_name)