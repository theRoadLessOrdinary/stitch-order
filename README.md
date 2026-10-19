# Stitch Order

An Inkscape extension for Ink/Stitch users. It sets the order objects are sewn in without moving them in their layers and groups.

Ink/Stitch sews objects in the order they appear in the document. Normally, changing the sewing order means rearranging your layers and groups. With this extension you number the objects instead, and keep your layers organized however you like.

## Menu

Extensions > Map's Edge Tools > Embroidery > Stitch Order

- **Add to Stitch Order**: select objects or groups in the order they should sew, then run this. They get the next numbers. An object that already has a number moves to the end.
- **Insert into Stitch Order**: puts the selected objects at the position you give. The numbers after them move up.
- **Remove from Stitch Order**: takes the number off the selected objects.
- **Clear Stitch Order**: takes the number off every object.
- **List Stitch Order**: shows the numbered objects in order.
- **Preview in Stitch Order**: opens the Ink/Stitch simulator, sewing in the numbered order.
- **Export in Stitch Order**: saves an embroidery file (DST, PES, JEF and the other Ink/Stitch formats) sewn in the numbered order, or an SVG of the document rearranged in that order. If you leave the file name empty, the file goes next to the SVG with the same name; an SVG gets " - stitch order" added to the name, so it never replaces your document.

If you number a group, everything inside it gets that number and sews in its usual order within the group. A number on an object inside the group overrides the group's number.

Preview and Export sew only the numbered objects. Objects without a number are left out.

## How it works

Each number is stored on its object as a `trlo:stitch_order` attribute, and it is saved with the SVG.

Preview and Export never change the open document. They build a temporary copy in which every object is taken out of its groups and placed in numbered order. Each object sits inside fresh copies of the groups it came from, with the same transforms, styles and clips, so it stays exactly where it was. Ink/Stitch then runs on that copy.

Ink/Stitch's own settings carry over to the copy:
- hidden layers and objects;
- Ignore Layer and Ignore Object;
- commands attached to objects, such as Stop and Trim.

Ink/Stitch's own Simulator and Stitch Plan Preview, run from the Ink/Stitch menu, still show the document order. Use Preview in Stitch Order to see the numbered order.

## Install

Copy this folder into your Inkscape user extensions folder. Ink/Stitch must be installed in the same extensions folder, as `inkstitch/`. Restart Inkscape.

Tested with Inkscape 1.4 and Ink/Stitch 3.2.2.
