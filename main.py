from time import perf_counter

if __name__ == "__main__":
    startup_marks = [("python_entry", perf_counter())]
    from app.__main__ import main

    main(startup_marks)
