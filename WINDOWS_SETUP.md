# Windows setup & scheduling

## 1. Install Python dependencies

Open Command Prompt or PowerShell in this folder and run:

```cmd
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you prefer a virtual environment:

```cmd
python -m venv venv
venv\Scripts\activate.bat
python -m pip install -r requirements.txt
```

## 2. Run manually

To generate images for tomorrow:

```cmd
python make_schedule.py
```

To generate for a specific date:

```cmd
python make_schedule.py --date 27.06.2026
```

Or simply double-click `run.bat`.

## 3. Schedule with Windows Task Scheduler

1. Press `Win + R`, type `taskschd.msc`, and press Enter.
2. In the right panel, click **Create Basic Task...**.
3. Give it a name, e.g., `KinoMinska Schedule Generator`.
4. Choose **Daily** as the trigger.
5. Set the time to run, e.g., `06:00` (morning before the cinema opens).
6. For **Action**, choose **Start a program**.
7. In **Program/script**, browse to and select `run.bat` from this folder.
8. In **Start in (optional)**, enter the full path to this folder (e.g., `C:\Users\YourName\Documents\kinominska-schedule`).
9. Finish the wizard.
10. (Optional) Open the task properties, go to the **Conditions** tab, and uncheck "Start the task only if the computer is on AC power" if you want it to run on battery.

The script will fetch tomorrow's schedule from `https://kinominska.by/objects/17` and save images like `27 Июня 1.jpg` in the same folder.

## 4. Notes

- Posters and metadata are cached in the `cache` folder, so repeat runs are faster.
- Fallback fonts are bundled in the `fonts` folder; the script also tries to use Arial if available on Windows.
- If you need the images saved elsewhere, add `--output "C:\Path\To\Folder"` to the command in `run.bat`.
