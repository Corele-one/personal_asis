"""Run with LibreOffice's system Python, inside a private network namespace."""

import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import uno
import unohelper
from com.sun.star.beans import PropertyValue
from com.sun.star.task import XInteractionHandler


class RejectInteraction(unohelper.Base, XInteractionHandler):
    def handle(self, request):
        abort = uno.getTypeByName("com.sun.star.task.XInteractionAbort")
        for continuation in request.getContinuations():
            if continuation.queryInterface(abort):
                continuation.select()
                break


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def main():
    os.umask(0o077)
    directory, fmt = Path(sys.argv[1]), sys.argv[2]
    target, filter_name = {"doc": ("docx", "Office Open XML Text"),
                          "xls": ("xlsx", "Calc MS Excel 2007 XML"),
                          "ppt": ("pptx", "Impress MS PowerPoint 2007 XML")}[fmt]
    pipe = "asis_" + secrets.token_hex(12)
    process = subprocess.Popen([sys.argv[3], "--headless", "--nologo", "--nodefault", "--norestore",
        "-env:UserInstallation=" + (directory / "profile").as_uri(),
        "--accept=pipe,name=" + pipe + ";urp;StarOffice.ServiceManager"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    desktop, document = None, None
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        context = None
        for _ in range(100):
            try:
                context = resolver.resolve("uno:pipe,name=" + pipe + ";urp;StarOffice.ComponentContext")
                break
            except Exception:
                if process.poll() is not None:
                    return 2
                time.sleep(.1)
        if context is None:
            return 2
        desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
        document = desktop.loadComponentFromURL((directory / ("input." + fmt)).as_uri(), "_blank", 0,
            (prop("Hidden", True), prop("ReadOnly", True),
             prop("MacroExecutionMode", uno.getConstantByName("com.sun.star.document.MacroExecMode.NEVER_EXECUTE")),
             prop("UpdateDocMode", uno.getConstantByName("com.sun.star.document.UpdateDocMode.NO_UPDATE")),
             prop("InteractionHandler", RejectInteraction())))
        if document is None:
            return 2
        document.storeToURL((directory / "out" / ("input." + target)).as_uri(),
                            (prop("FilterName", filter_name), prop("Overwrite", False)))
        return 0
    except Exception:
        return 2
    finally:
        try:
            if document:
                document.close(True)
            if desktop:
                desktop.terminate()
        except Exception:
            pass
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
