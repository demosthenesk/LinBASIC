LinBASIC @VERSION@ for Windows (@BITS@-bit, portable)
=================================================

LinBASIC is a QB 4.5 compatible BASIC compiler and IDE. This is the portable
Windows edition: nothing is installed, and nothing is written outside this
folder (settings are kept in the "settings" folder).

  LinBASIC.exe   the IDE (editor, Start F5, Make EXE, Check Syntax, SUBs, help)
  lbc.exe        the command-line compiler
  examples\      example programs

Requirements
------------
* Windows 7 SP1 or later (32-bit edition: 32- or 64-bit Windows;
  64-bit edition: 64-bit Windows only).
* On Windows 7 the updates KB2533623 (or KB3063858) and KB2999226 (Universal
  C Runtime) must be installed. Windows Update installs both; Windows 8.1, 10
  and 11 already have them.

Getting started
---------------
1. Extract the whole zip file to a folder you can write to (for example your
   Documents folder or a USB stick), not into "Program Files".
2. Double-click LinBASIC.exe, open examples\SHAPES.BAS and press F5.
3. LinBASIC -> Make EXE File... makes a stand-alone .exe:
   * Windows - DOS window (.exe): the program opens its own DOS screen window
   * Windows - cmd console (.exe): a program for the cmd.exe console
   The @BITS@-bit edition makes @BITS@-bit programs.

Command line
------------
  lbc -o HELLO.EXE examples\HELLO.BAS              DOS window program
  lbc --console -o GUESS.EXE examples\GUESS.BAS    cmd console program
  lbc --help                                       all options

Help
----
No help files are included (the QB 4.5 help files are Microsoft's work). If
you own QB 4.5, choose LinBASIC -> Help -> Set Help Folder... and select the
folder with QB45ADVR.HLP, QB45QCK.HLP and QB45ENER.HLP.

About this edition
------------------
Qt 6 needs Windows 10, so the Windows IDE runs on Qt 5.15 with Python 3.8,
the last versions that support Windows 7. The Python 3.8 build comes from
https://github.com/adang1345/PythonVista (unofficial builds that keep Windows 7
support). Programs are compiled with the bundled Tiny C Compiler.

Source code, Linux AppImages and documentation:
  https://github.com/demosthenesk/LinBASIC

LinBASIC is free software under the GNU General Public License v3.0 or later
(see LICENSE.txt). It is not affiliated with or endorsed by Microsoft.
