import 'package:bitsdojo_window/bitsdojo_window.dart';
import 'package:flutter/material.dart';

class AppTitleBar extends StatelessWidget {
  final List<String> zipDirs;
  final TextEditingController sourceDirController;
  final String? selectedZipDir;
  final TextEditingController tagController;
  final bool isProcessing;
  final ValueChanged<String?> onZipDirChanged;
  final VoidCallback? onStart;
  final VoidCallback onPickSourceDir;
  final VoidCallback onReset;

  const AppTitleBar({
    super.key,
    required this.zipDirs,
    required this.sourceDirController,
    required this.selectedZipDir,
    required this.tagController,
    required this.isProcessing,
    required this.onZipDirChanged,
    required this.onStart,
    required this.onPickSourceDir,
    required this.onReset,
  });

  InputDecoration _fieldDecoration({
    required String hintText,
    Widget? prefixIcon,
    double horizontalPadding = 12,
    double verticalPadding = 10,
  }) {
    return InputDecoration(
      hintText: hintText,
      hintStyle: const TextStyle(color: Colors.white38, fontSize: 12),
      filled: true,
      fillColor: const Color(0xff152235),
      prefixIcon: prefixIcon == null
          ? null
          : Padding(
              padding: const EdgeInsets.only(left: 10, right: 8),
              child: prefixIcon,
            ),
      prefixIconConstraints: const BoxConstraints(minWidth: 0, minHeight: 0),
      contentPadding: EdgeInsets.symmetric(
        horizontal: horizontalPadding,
        vertical: verticalPadding,
      ),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Color(0xff2c405d)),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Color(0xff2c405d)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Color(0xff3b82f6), width: 1.2),
      ),
    );
  }

  BoxDecoration _fieldBoxDecoration() {
    return BoxDecoration(
      color: const Color(0xff152235),
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: const Color(0xff2c405d)),
    );
  }

  ButtonStyle _actionStyle({
    required Color background,
    required Color foreground,
    required Color border,
  }) {
    return OutlinedButton.styleFrom(
      backgroundColor: background,
      foregroundColor: foreground,
      side: BorderSide(color: border),
      padding: const EdgeInsets.symmetric(horizontal: 14),
      minimumSize: const Size(0, 38),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      textStyle: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 56,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [Color(0xff09111d), Color(0xff0b1522), Color(0xff08101a)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          border: Border(bottom: BorderSide(color: Color(0xff18304b))),
        ),
        child: ClipRect(
          child: Row(
            children: [
              SizedBox(
                width: 154,
                child: MoveWindow(
                  child: Row(
                    children: const [
                      Icon(
                        Icons.bolt_outlined,
                        color: Color(0xff4fc3f7),
                        size: 18,
                      ),
                      SizedBox(width: 7),
                      Text(
                        "LogAgent",
                        style: TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w700,
                          fontSize: 14,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      SizedBox(
                        width: 270,
                        child: Container(
                          height: 36,
                          padding: const EdgeInsets.all(3),
                          decoration: BoxDecoration(
                            color: const Color(0xff0c1624),
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: const Color(0xff27415f)),
                          ),
                          child: TextField(
                            controller: sourceDirController,
                            readOnly: true,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 12,
                            ),
                            decoration: _fieldDecoration(
                              hintText: "项目源码目录",
                              prefixIcon: const Icon(
                                Icons.source_outlined,
                                size: 16,
                                color: Colors.white54,
                              ),
                              horizontalPadding: 10,
                              verticalPadding: 7,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      Tooltip(
                        message: "选择项目源码目录",
                        child: SizedBox(
                          width: 36,
                          height: 36,
                          child: OutlinedButton(
                            onPressed: onPickSourceDir,
                            style:
                                _actionStyle(
                                  background: const Color(0xff122033),
                                  foreground: Colors.white70,
                                  border: const Color(0xff2c405d),
                                ).copyWith(
                                  padding: const WidgetStatePropertyAll(
                                    EdgeInsets.zero,
                                  ),
                                  minimumSize: const WidgetStatePropertyAll(
                                    Size(36, 36),
                                  ),
                                ),
                            child: const Icon(Icons.folder_open, size: 17),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 260,
                        child: Container(
                          height: 38,
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          decoration: _fieldBoxDecoration(),
                          child: DropdownButtonHideUnderline(
                            child: DropdownButton<String>(
                              value: zipDirs.contains(selectedZipDir)
                                  ? selectedZipDir
                                  : null,
                              isExpanded: true,
                              icon: const Icon(
                                Icons.expand_more,
                                color: Colors.white54,
                              ),
                              dropdownColor: const Color(0xff101c2b),
                              hint: Row(
                                children: const [
                                  Icon(
                                    Icons.folder_zip_outlined,
                                    size: 16,
                                    color: Colors.white54,
                                  ),
                                  SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      "拖入 ZIP 后自动读取目录",
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: Colors.white38,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              items: zipDirs
                                  .map(
                                    (dir) => DropdownMenuItem(
                                      value: dir,
                                      child: Text(
                                        dir,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: Colors.white70,
                                        ),
                                      ),
                                    ),
                                  )
                                  .toList(),
                              onChanged: zipDirs.isEmpty
                                  ? null
                                  : onZipDirChanged,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 132,
                        child: TextField(
                          controller: tagController,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                          ),
                          decoration: _fieldDecoration(
                            hintText: "Tag关键词",
                            prefixIcon: const Icon(
                              Icons.sell_outlined,
                              size: 16,
                              color: Colors.white54,
                            ),
                            verticalPadding: 8,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        height: 36,
                        child: OutlinedButton.icon(
                          onPressed: onReset,
                          icon: const Icon(Icons.refresh_rounded, size: 15),
                          label: const Text(
                            "重置",
                            style: TextStyle(fontSize: 12),
                          ),
                          style: _actionStyle(
                            background: const Color(0xff122033),
                            foreground: Colors.white70,
                            border: const Color(0xff2c405d),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 6),
              SizedBox(
                width: 114,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    WindowButton(
                      colors: WindowButtonColors(
                        iconNormal: Colors.white54,
                        mouseOver: const Color(0xff24344a),
                        mouseDown: const Color(0xff30445f),
                      ),
                      icon: Icons.remove,
                      onPressed: () => appWindow.minimize(),
                    ),
                    WindowButton(
                      colors: WindowButtonColors(
                        iconNormal: Colors.white54,
                        mouseOver: const Color(0xff24344a),
                        mouseDown: const Color(0xff30445f),
                      ),
                      icon: Icons.crop_square,
                      onPressed: () => appWindow.maximizeOrRestore(),
                    ),
                    WindowButton(
                      colors: WindowButtonColors(
                        iconNormal: Colors.white54,
                        mouseOver: const Color(0xffda3b3b),
                        mouseDown: const Color(0xffbf2f2f),
                      ),
                      icon: Icons.close,
                      onPressed: () => appWindow.close(),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class WindowButton extends StatelessWidget {
  final WindowButtonColors colors;
  final IconData icon;
  final VoidCallback onPressed;

  const WindowButton({
    super.key,
    required this.colors,
    required this.icon,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return MouseRegion(
      cursor: SystemMouseCursors.click,
      child: GestureDetector(
        onTap: onPressed,
        child: Container(
          width: 36,
          height: 38,
          color: Colors.transparent,
          child: Center(child: Icon(icon, color: colors.iconNormal, size: 18)),
        ),
      ),
    );
  }
}
