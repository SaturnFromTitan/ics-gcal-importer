# .ics importer for Google Calendar

Many services and companies don't integrate with Google Calendar.
Instead they provide a download link to an `.ics` file which can be imported manually into the calendar via the gcal UI.

That's too cumbersome for me! This small utility imports all `.ics` files from the local `~/Downloads` directory of my mac and imports them to my primary calendar.

## Execution

The following prerequisites have to be installed:

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python Package Manager)
- [just](https://github.com/casey/just) (Command Runner)

Now you can run the CLI via

```sh
uv import-ics
```

### Installation

There's no use case to distribute CLI to PyPI (there are no other users and I didn't want to worry about compatibility with earlier Python versions).
It's still handy to install it locally so that you don't have to `cd` into the project.
Luckily this is very easy with `uv`:

```sh
uv tool install --editable .
```

And now you can run the following command regardless of your current working directory:

```sh
import-ics
```

Please note that the path where it searches for .ics files can be overwritten if needed.
