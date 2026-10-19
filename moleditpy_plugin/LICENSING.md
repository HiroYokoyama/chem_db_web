# Molibrary Browser plugin licensing

The copyright holder, Hiromichi Yokoyama / HiroYokoyama, authorizes the
first-party Molibrary Browser Python plugin distributed with this notice under
**LGPL-3.0-or-later**. `LICENSE` contains LGPLv3's additional permissions and
`COPYING` its incorporated GPLv3 terms. Retain both texts and existing notices
when redistributing the plugin. Historical releases retain their original grants.

This permission covers `molibrary_plugin.py`, including the first-party geometry
helper adapted from MoleditPy. It does not relicense third-party libraries or the
separate Molibrary web application, which retains the repository's GPLv3 license.
The plugin and server communicate through HTTP; the plugin does not copy or
import the server implementation.

PySide6/Qt (LGPLv3 option), RDKit (BSD-family), and the host's libraries retain
their respective licenses. The single-file plugin release does not bundle these
libraries; keep their own notices and source/replacement rights when distributing
them in a combined application. The server's Flask, Werkzeug and browser editor
assets likewise retain their own terms. No dependency is relicensed by this grant.

Independent MoleditPy plugins may choose their own licenses under the host's
documented API permission. This plugin's LGPL choice does not impose that choice
on other independently developed plugins.
