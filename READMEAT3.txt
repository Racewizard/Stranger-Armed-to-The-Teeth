===============================================================================
  STRANGER: ARMED TO THE TEETH  (AT3)  -  v0.2
  A modding launcher for Oddworld: Stranger's Wrath HD
===============================================================================

AT3 is an extension of SWSE (Stranger's Wrath Script Extender). It does not
contain SWSE, nor does it contain any of Oddworld: Stranger's Wrath HD's files.


~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

MY PERSONAL MESSAGE TO YOU

Hey moron welcome to Stranger AT3. I'll be dead honest with you and say this piece
of junk is barely held together with claude prompts hopes and dreams. If you have
problems with it, let me know on the SWSE Discord: https://discord.gg/37zjaxPp68

In order to see your changes in game, you'll need to select "Apply Changes" then
open the launcher either through AT3 or just normally on steam. YOU NEED TO START
A NEW GAME TO APPLY YOUR CHANGES! Also, for spawning new characters and prompts,
you'll want to use SWSE's "writepos" command. Happy hunting.

-------------------------------------------------------------------------------
  WHAT YOU NEED FIRST
-------------------------------------------------------------------------------

1. Oddworld: Stranger's Wrath HD  (the retail release)

2. SWSE installed and working
   AT3 depends on it. Install SWSE first and confirm the game runs.

3. Python 3.8 or newer, on your PATH
   AT3 does the heavy file work through Python scripts in ModTools\.
   Get it from python.org. During install, tick "Add Python to PATH".

   To check: open a Command Prompt and type
       python --version
   If that prints a version number you are ready. If it says the command is
   not recognized, Python is either missing or not on PATH, and AT3 will tell
   you so rather than failing silently.


-------------------------------------------------------------------------------
  INSTALLING
-------------------------------------------------------------------------------

Drag BOTH folders from this bundle into your Stranger's Wrath game folder -
the one containing Launcher.exe:

    <game folder>\
        Launcher.exe            (already there)
        stranger.exe            (already there)
        data\                   (already there)
        StrangerAT3\            <-- drop this in
        ModTools\               <-- and this one

If you already have a ModTools folder from another tool, merge rather than
replace; AT3 only adds the 17 files it needs.

That is the whole install. Run StrangerAT3\Stranger AT3.exe.

A typical Steam path looks like:
    C:\SteamLibrary\steamapps\common\Stranger's Wrath\


-------------------------------------------------------------------------------
  IF SOMETHING GOES WRONG
-------------------------------------------------------------------------------

StrangerAT3\at3_debug.log records what the launcher did. If a button seems to
do nothing, look there first.

"Python was not found on PATH"
    Install Python 3.8+ and tick "Add Python to PATH", then restart AT3.

A region will not load
    Press RESTORE VANILLA. If it persists, verify your SWSE install.

Changes did not appear in game
    Press APPLY CHANGES before launching, and close AT3 before playing - it
    rewrites files when you apply, which can change what you are testing.


-------------------------------------------------------------------------------
  WHAT IS IN THIS BUNDLE
-------------------------------------------------------------------------------

    StrangerAT3\
        Stranger AT3.exe          the launcher
        header_logo.png           its banner
        *.csv                     ammo tables, region and prop names,
                                  custom hashes, randomizer settings
        RegionData\               catalogues of the game's characters, props,
                                  spawns and ambience - readability tools,
                                  not game data
        PropPlacements\           your edits, empty until you make some
        Presets\                  AT3 Official, and its recipe

    ModTools\                     17 Python scripts the launcher calls

    READMEAT3.txt                 this file

No file in this bundle is from Oddworld: Stranger's Wrath.

===============================================================================
