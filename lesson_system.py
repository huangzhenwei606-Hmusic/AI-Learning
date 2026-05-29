students = {
    "Emma": 10,
    "Tom": 8,
    "Sophia": 2
}


def deduct_lesson(student):

    students[student] -= 1

    print(f"{student} finished a lesson.")

    print(f"Remaining lessons: {students[student]}")

    if students[student] <= 2:

        print("⚠️ Contact parent for renewal.")

    print("---------")


deduct_lesson("Emma")

deduct_lesson("Sophia")