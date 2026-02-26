# Iftar-Slot-Checker

**Iftar Slot Checker** is a `simple`, `community-focused` tool designed to help you secure your spot at the `daily iftar` at IZA. With an Islamic spirit of togetherness 🤲 and community care, it sends you a timely Telegram notification 🔔 when a spot opens up. This way, you can join the blessed iftar gatherings 🕌 without the last-minute rush, ensuring everyone in the community can benefit from this shared experience.

Join the Telegram group - [Iftar at IZA](https://t.me/+M43iaRqaMv9hNGUy)

### Running tests

Tests simulate the IZA site with fixture HTML and mock HTTP/Telegram. From the project root, with the `iftarslotchecker` conda env activated (or using its Python):

```bash
python -m pytest tests/ -v
```

Example with explicit env on Windows:

```bash
C:\Users\deathstar\miniconda3\envs\iftarslotchecker\python.exe -m pytest tests\ -v
```