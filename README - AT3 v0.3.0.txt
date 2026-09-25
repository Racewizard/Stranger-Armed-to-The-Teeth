================================================================
        Stranger: Armed to the Teeth (AT3)  -  v0.3.0
        for Oddworld: Stranger's Wrath HD (Steam)
                       By Racewizard
================================================================

AT3 is a free, open-source mod toolkit for Stranger's Wrath HD. It is an
extension of SWSE (the Stranger's Wrath Script Extender). SWSE is separate
software by another developer and is NOT included - AT3 requires it.

With AT3 you can change the game's rules, ammo, spawns, props, ambience and
characters - build new characters and weapons, make them drop custom loot,
and share the whole setup with other players as a single preset file.

AT3 is free and always will be. If you paid for it, you were scammed.


REQUIREMENTS
------------
  * Oddworld: Stranger's Wrath HD (the Steam version).
  * Windows.
  * SWSE (Stranger's Wrath Script Extender), installed first - get it from
    its own release. AT3 will not start without it.
  * Nothing else. AT3 brings its own copy of Python - you do NOT need to
    install Python. (See "About the bundled Python" below.)


INSTALL
-------
0. Install SWSE first, following its own instructions.

1. Find your game folder. In Steam: right-click Stranger's Wrath ->
   Manage -> Browse local files. It contains a "bin" and a "data" folder.

2. Extract EVERYTHING from this zip into that game folder. When Windows
   asks to merge or replace folders, say YES. Nothing of the game is
   deleted - AT3 only adds files, and backs up anything it changes.

3. Run  StrangerAT3\Stranger AT3.exe .


HOW IT WORKS
------------
  * Open a tool from Gameplay Editor, Map Editor or Creator on the right.
  * Every tool window has CONFIRM and CANCEL at the bottom.
      CONFIRM writes your changes to the game straight away.
      CANCEL (or closing the window) throws away what you changed in it.
  * PRESETS (left) saves everything you have set up, in every tool, as one
    file - and loads it back.
  * RESTORE VANILLA undoes every change AT3 has made to the game.
  * OPEN LAUNCHER starts the game.


WHAT'S NEW IN 0.3.0
-------------------
  * Starts in about two seconds. Heavy game data is only read when a tool
    that needs it is opened.
  * CONFIRM / CANCEL in every tool window replaces the single APPLY CHANGES
    button. Loading a preset applies it immediately (after asking).
  * Presets hold everything: game rules, ammo, spawn edits, props, the
    randomizer, ambience, ported props, and every character and weapon
    you built in the Creator - in one .json file you can send to anyone.
    Characters travel as small patches against the game's own records, so
    no game data is ever shared.
  * PRESETS menu: Import, Export, Overwrite, Delete, Open Presets Folder.
  * Custom sprays: design what a character drops (Creator > Character >
    Dropped Loot > "Custom spray..."). The spray dials are experimental -
    what each one does is for you to discover. Tell us what you find!
  * Gib effects: choose what a character bursts into - default gibs,
    Shock Tank chunks, turret chunks or mine cart chunks.
  * Prop Editor: "Port geometry from another region..." brings any mesh in
    the game into the region you are editing.
  * Ambience Config now shows the values actually in the game, and putting
    a value back to its original really puts it back.
  * Gameplay Editor > Character Studio is now "Character Catalogue".
  * No Python install needed any more.


SHARING PRESETS
---------------
  PRESETS -> the arrow button next to a preset exports it. Send the file.
  PRESETS -> Import Preset... adds one someone sent you. Then click it to
  load it. A preset built on a different AT3 install rebuilds its custom
  characters from YOUR copy of the game; if your game files differ from
  theirs, AT3 refuses that character rather than corrupting anything, and
  tells you which one.


UNINSTALL
---------
1. Run AT3 and press RESTORE VANILLA.
2. Delete the StrangerAT3 and ModTools folders from the game folder.
   SWSE is separate; remove it following its own instructions if you wish.
   Steam -> Properties -> Installed Files -> "Verify integrity of game
   files" also restores any game file to its original.


ABOUT THE BUNDLED PYTHON
------------------------
AT3's tools are written in Python. So that you do not have to install it,
AT3 includes its own private copy in StrangerAT3\python\ : the official
CPython 3.14 for Windows from python.org, with unused parts removed. It does
not install anything, change your PATH or registry, or affect any other
Python on your computer. It is covered by the Python Software Foundation
License - see StrangerAT3\python\LICENSE.txt and
StrangerAT3\THIRD_PARTY_NOTICES.txt.


OPEN SOURCE
-----------
AT3 is open source. The launcher's full source is
StrangerAT3\Stranger_AT3_v2.ps1 (compiled to the .exe by build.ps1), and
every tool in ModTools\ is plain Python source.

AT3 is an unofficial fan project, not affiliated with or endorsed by
Oddworld Inhabitants or Just Add Water. Oddworld: Stranger's Wrath is
(C) Oddworld Inhabitants, Inc. AT3 does not contain or redistribute any
game data.


HELP
----
  Discord:  https://discord.gg/TWHzP924wE
  If something goes wrong, include StrangerAT3\at3_debug.log.
