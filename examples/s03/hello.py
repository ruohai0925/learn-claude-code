def greet(name: str = "World") -> None:
    """Print a greeting message to the console.

    Args:
        name: The name to greet. Defaults to "World".
    """
    print(f"Hello, {name}!")


def main() -> None:
    """Entry point for the hello script."""
    greet()


if __name__ == "__main__":
    main()
