import dataclasses
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from bot7685_ext.wplace.consts import ALL_COLORS
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.log import logger
from app.utils import WplacePixelCoords

from .config import CONFIG_FILE, GUI_ICO, TEMPLATES_DIR, ensure_data_dirs, read_config, write_config
from .image import ImageDropLabel
from .user import create_user


class ConfigInitWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("初始化 config.json")

        # 尝试设置窗口图标（确保传入字符串路径）
        try:
            if GUI_ICO.is_file():
                self.setWindowIcon(QIcon(str(GUI_ICO)))
        except Exception as exc:
            logger.debug(f"无法设置窗口图标: {exc}")

        # 浏览器选择
        self.browser_cb = QComboBox()
        self.browser_cb.addItems(["chromium", "chrome", "msedge", "firefox", "webkit"])

        # 控制台日志等级选择
        self.log_level_cb = QComboBox()
        self.log_level_cb.addItems(["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level_cb.setCurrentText("INFO")

        # 代理地址
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("Proxy Server URL (e.g., http://127.0.0.1:7890)")

        # 保存按钮
        save_btn = QPushButton("保存 config.json")
        save_btn.setFixedWidth(125)
        save_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        save_btn.clicked.connect(self.save_config)

        # 用户列表与控件
        self.users_list = QListWidget()
        self.users_list.currentRowChanged.connect(self.on_user_selected)
        add_user_btn = QPushButton("新增用户")
        add_user_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        add_user_btn.clicked.connect(self.add_user)
        remove_user_btn = QPushButton("删除用户")
        remove_user_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        remove_user_btn.clicked.connect(self.remove_user)

        # 凭证输入框
        self.token_edit = QTextEdit()
        self.token_edit.setPlaceholderText("token")
        self.cf_edit = QTextEdit()
        self.cf_edit.setPlaceholderText("cf_clearance")

        # 颜色偏好配置
        self.colors_list = QListWidget()
        self.colors_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.colors_list.setMinimumHeight(120)

        # 导入颜色名称列表
        self.all_colors = list(ALL_COLORS.keys())
        add_color_btn = QPushButton("添加颜色")
        add_color_btn.clicked.connect(self.add_color)
        remove_color_btn = QPushButton("移除颜色")
        remove_color_btn.clicked.connect(self.remove_color)
        move_up_btn = QPushButton("上移")
        move_up_btn.clicked.connect(self.move_color_up)
        move_down_btn = QPushButton("下移")
        move_down_btn.clicked.connect(self.move_color_down)

        # 坐标：单行输入 Blue Marble 格式
        self.coords_edit = QLineEdit()
        self.coords_edit.setPlaceholderText("(Tl X: 12, Tl Y: 34, Px X: 56, Px Y: 78)")

        # file_id 输入（template.file_id）
        self.file_id_edit = QLineEdit()
        self.file_id_edit.setPlaceholderText("template file_id (will save as data/templates/{file_id}.png)")

        # 图片拖放区（每用户预览）
        self.img_label = ImageDropLabel()
        upload_btn = QPushButton("选择图片...")
        upload_btn.clicked.connect(self.choose_image)

        # 系统配置布局
        system_box = QGroupBox()
        system_box.setTitle("系统配置")
        system_box_layout = QVBoxLayout()
        system_box_h1 = QHBoxLayout()
        system_browser_v = QVBoxLayout()
        system_browser_v.addWidget(QLabel("浏览器选择 (chromium,firefox,webkit需另外安装)"))
        system_browser_v.addWidget(self.browser_cb)
        system_box_h1.addLayout(system_browser_v)
        system_log_level_v = QVBoxLayout()
        system_log_level_v.addWidget(QLabel("控制台日志等级"))
        system_log_level_v.addWidget(self.log_level_cb)
        system_box_h1.addLayout(system_log_level_v)
        system_box_layout.addLayout(system_box_h1)
        system_proxy_v = QVBoxLayout()
        system_proxy_v.addWidget(QLabel("网络请求代理地址 (可选)"))
        system_proxy_v.addWidget(self.proxy_edit)
        system_box_layout.addLayout(system_proxy_v)
        system_box.setLayout(system_box_layout)
        system_layout = QHBoxLayout()
        system_layout.addWidget(system_box)
        system_layout.addWidget(save_btn)

        # 用户列表布局
        users_layout = QVBoxLayout()
        users_layout.addWidget(QLabel("用户列表 (users list)"))
        users_h = QHBoxLayout()
        users_h.addWidget(self.users_list)
        users_ctrl_v = QVBoxLayout()
        users_ctrl_v.addWidget(add_user_btn)
        users_ctrl_v.addWidget(remove_user_btn)
        users_h.addLayout(users_ctrl_v)
        users_layout.addLayout(users_h)

        # 凭证布局
        cred_box = QGroupBox()
        cred_box.setTitle("登录凭证 (credentials)")
        cred_layout = QVBoxLayout()
        cred_layout.addWidget(QLabel("token ( wplace Cookies 中的 j )"))
        cred_layout.addWidget(self.token_edit)
        cred_layout.addWidget(QLabel("cf_clearance ( wplace Cookies 中的 cf_clearance )"))
        cred_layout.addWidget(self.cf_edit)
        cred_box.setLayout(cred_layout)

        # 颜色偏好布局
        colors_box = QGroupBox()
        colors_box.setTitle("颜色偏好 (preferred_colors)")
        colors_layout = QVBoxLayout()
        colors_layout.addWidget(QLabel("选择优先使用的颜色顺序（可选）"))
        colors_layout.addWidget(self.colors_list)
        colors_btn_layout = QHBoxLayout()
        colors_btn_layout.addWidget(add_color_btn)
        colors_btn_layout.addWidget(remove_color_btn)
        colors_btn_layout.addWidget(move_up_btn)
        colors_btn_layout.addWidget(move_down_btn)
        colors_layout.addLayout(colors_btn_layout)
        colors_box.setLayout(colors_layout)

        # 模板布局
        template_box = QGroupBox()
        template_box.setTitle("模板图片 (template)")
        template_layout = QVBoxLayout()
        template_layout.addWidget(QLabel("模板坐标 (coords)"))
        template_layout.addWidget(self.coords_edit)
        template_layout.addWidget(QLabel("模板图片名字"))
        template_layout.addWidget(self.file_id_edit)
        template_image_header = QHBoxLayout()
        template_image_header.addWidget(QLabel("模板图片预览(按住左键框选区域，按住右键移动图片，鼠标滚轮缩放图片)"))
        template_image_header.addStretch()
        template_image_header.addWidget(upload_btn)
        template_layout.addLayout(template_image_header)
        template_layout.addWidget(self.img_label)
        template_box.setLayout(template_layout)

        # 用户配置布局
        user_config_box = QGroupBox()
        user_config_box.setTitle("用户配置")
        user_config_layout = QHBoxLayout()
        user_config_left = QVBoxLayout()
        user_config_left.addLayout(users_layout)
        user_config_left.addSpacing(10)
        user_config_left.addWidget(cred_box)
        user_config_left.addSpacing(10)
        user_config_left.addWidget(colors_box)
        user_config_layout.addLayout(user_config_left)
        user_config_layout.addSpacing(10)
        user_config_layout.addWidget(template_box)
        user_config_widget = QWidget()
        user_config_widget.setLayout(user_config_layout)
        QVBoxLayout(user_config_box).addWidget(user_config_widget)

        # 主布局
        main = QVBoxLayout()
        main.addLayout(system_layout)
        main.addSpacing(15)
        main.addWidget(user_config_box)

        self.setLayout(main)

        # 内部状态
        self.users = []

        ensure_data_dirs()
        self.load_config()
        # track last selected row for auto-save behavior
        self.last_selected_row = self.users_list.currentRow() if self.users_list.count() > 0 else -1

    def choose_image(self) -> None:
        fp, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if fp:
            self.img_label.set_image(fp)

    def load_config(self) -> None:
        cfg = read_config()

        # 载入 users 列表（新格式）
        users = cfg.get("users")
        if isinstance(users, list):
            self.users = users
            self.users_list.clear()
            for u in self.users:
                self.users_list.addItem(u.get("identifier", ""))
            if self.users_list.count() > 0:
                # 选择第一个用户
                self.users_list.setCurrentRow(0)
        else:
            # 兼容旧的单用户格式
            tmpl = cfg.get("template")
            creds = cfg.get("credentials")
            identifier = cfg.get("identifier", "default")
            if tmpl:
                u = {"identifier": identifier, "template": tmpl, "credentials": creds or {}}
                self.users = [u]
                self.users_list.clear()
                self.users_list.addItem(identifier)
                self.users_list.setCurrentRow(0)

        # 全局浏览器设置
        if (browser := cfg.get("browser")) and (idx := self.browser_cb.findText(browser)) != -1:
            self.browser_cb.setCurrentIndex(idx)

        # 全局日志等级设置
        if (log_level := cfg.get("log_level")) and (idx := self.log_level_cb.findText(log_level)) != -1:
            self.log_level_cb.setCurrentIndex(idx)

        # 全局代理设置
        if proxy := cfg.get("proxy"):
            self.proxy_edit.setText(proxy)

    def save_config(self) -> bool:
        # 保存当前选中用户的数据到 self.users 并写回 config.json
        row = self.users_list.currentRow()
        if row < 0 or row >= len(self.users):
            QMessageBox.warning(self, "未选中用户", "请先在用户列表中选择或新增一个用户")
            return False

        # 解析坐标
        coords_text = self.coords_edit.text().strip()
        try:
            coords = WplacePixelCoords.parse(coords_text)
        except Exception:
            text = "无法解析模板坐标，请使用类似 '(Tl X: 1719, Tl Y: 855, Px X: 320, Px Y: 24)' 的格式"
            QMessageBox.warning(self, "坐标解析失败", text)
            return False

        # 先获取图片路径和 token
        src = getattr(self.img_label, "filepath", None)
        token = self.token_edit.toPlainText().strip()

        if not token:
            QMessageBox.warning(self, "缺少 token", "请填写 token（wplace Cookies 中的 j）")
            return False

        file_id = self.file_id_edit.text().strip()

        if not file_id:
            try:
                file_id = Path(str(src)).stem
                self.file_id_edit.setText(file_id)
            except Exception:
                text = "请填写 template.file_id（用于保存为 data/templates/{file_id}.png）"
                QMessageBox.warning(self, "缺少 file_id", text)
                return False

        if not TEMPLATES_DIR.exists():
            TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        dest = TEMPLATES_DIR / f"{file_id}.png"
        selected_area_val = None
        if src:
            # 确保模板文件存在：若目标不存在则复制上传的源文件过去
            if not dest.exists():
                try:
                    shutil.copy2(str(src), dest)
                except Exception as e:
                    QMessageBox.warning(self, "保存图片失败", f"无法保存图片: {e}")
                    return False

            # 获取选区（原始图片坐标）
            img = QImage(str(dest))
            sel = self.img_label.create_masked_template()

            # 如果没有选区，默认使用整张图片尺寸
            if sel is None:
                try:
                    if not img.isNull():
                        sel = (0, 0, img.width(), img.height())
                        if int(sel[2]) >= img.width() or int(sel[3]) >= img.height():
                            sel = (0, 0, img.width(), img.height())
                except Exception:
                    sel = None
            # 保存到本地变量，后面会赋值到 users 列表中的 user
            selected_area_val = sel
        else:
            # 没有上传新图片，且目标模板不存在 -> 提示错误
            if not dest.exists():
                QMessageBox.warning(self, "缺少图片", "请上传或拖放模板图片到预览区")
                return False

        user = self.users[row]
        tp: dict = user.setdefault("template", {})
        tp["file_id"] = file_id
        tp["coords"] = dataclasses.asdict(coords)
        user["credentials"] = {
            "token": self.token_edit.toPlainText().strip(),
            "cf_clearance": self.cf_edit.toPlainText().strip(),
        }

        # 写入选区信息（如果有）到 user.selected_area
        user["selected_area"] = selected_area_val

        # 保存颜色偏好
        preferred_colors = []
        for i in range(self.colors_list.count()):
            item = self.colors_list.item(i)
            if item:
                preferred_colors.append(item.text())
        if preferred_colors:
            user["preferred_colors"] = preferred_colors
        else:
            user.pop("preferred_colors", None)

        # 将 users 和系统配置项写回配置
        cfg = {
            "users": self.users,
            "browser": self.browser_cb.currentText(),
            "log_level": self.log_level_cb.currentText(),
            "proxy": self.proxy_edit.text().strip() or None,
        }

        if not write_config(cfg):
            QMessageBox.critical(self, "保存失败", "写入配置失败")
            return False

        QMessageBox.information(self, "保存成功", f"配置已保存到:\n{CONFIG_FILE}\n模板图片目录: {TEMPLATES_DIR}")

        item = self.users_list.item(row)
        if item:
            item.setText(user.get("identifier", ""))
        return True

    def write_config_to_disk(self) -> bool:
        cfg = {
            "users": self.users,
            "browser": self.browser_cb.currentText(),
            "log_level": self.log_level_cb.currentText(),
            "proxy": self.proxy_edit.text().strip() or None,
        }
        return write_config(cfg)

    def add_user(self) -> None:
        text, ok = QInputDialog.getText(self, "新增用户", "identifier:")
        if not ok:
            return
        identifier = text.strip()
        if not identifier:
            return
        for u in self.users:
            if u.get("identifier") == identifier:
                QMessageBox.warning(self, "已存在", "该用户已存在")
                return
        user = create_user(identifier)
        self.users.append(user)
        self.users_list.addItem(identifier)
        # 立即将新用户写入磁盘
        if not self.write_config_to_disk():
            self.users.pop()
            self.users_list.takeItem(self.users_list.count() - 1)
            return
        self.users_list.setCurrentRow(self.users_list.count() - 1)

    def remove_user(self) -> None:
        row = self.users_list.currentRow()
        if row < 0 or row >= len(self.users):
            return
        identifier = self.users[row].get("identifier", "")
        ret = QMessageBox.question(
            self,
            "删除用户",
            f"确定删除 identifier='{identifier}' 的所有用户记录？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {"users": self.users}
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"读取配置文件失败: {e}")
            return

        users_on_disk = cfg.get("users", []) if isinstance(cfg.get("users", []), list) else []
        new_users = [u for u in users_on_disk if u.get("identifier") != identifier]

        if len(new_users) == len(users_on_disk):
            self.users = [u for u in self.users if u.get("identifier") != identifier]
        else:
            cfg["users"] = new_users
            if not write_config(cfg):
                QMessageBox.critical(self, "写入失败", "写入配置失败")
                return
            self.users = new_users

        self.users_list.clear()
        for u in self.users:
            self.users_list.addItem(u.get("identifier", ""))

        self.coords_edit.clear()
        self.file_id_edit.clear()
        self.token_edit.clear()
        self.cf_edit.clear()
        self.colors_list.clear()
        self.img_label.setText("拖放图片到此处或点击上传")
        self.img_label.filepath = None

        QMessageBox.information(self, "删除完成", f"所有 identifier='{identifier}' 的记录已删除")

    def on_user_selected(self, row: int) -> None:
        # 处理上一次选择的自动保存
        prev = getattr(self, "last_selected_row", -1)
        if prev != -1 and prev != row and prev < len(self.users):
            u_prev = self.users[prev]
            tmpl = u_prev.get("template", {})
            coords = tmpl.get("coords", {})
            tlx = coords.get("tlx")
            tly = coords.get("tly")
            pxx = coords.get("pxx")
            pxy = coords.get("pxy")
            stored_coords = (
                f"(Tl X: {tlx}, Tl Y: {tly}, Px X: {pxx}, Px Y: {pxy})"
                if all(isinstance(v, int) for v in (tlx, tly, pxx, pxy))
                else ""
            )
            # 获取当前颜色列表
            current_colors = [
                item.text() for i in range(self.colors_list.count()) if (item := self.colors_list.item(i))
            ]
            stored_colors: list[str] = u_prev.get("preferred_colors", [])

            changed = (
                self.coords_edit.text().strip() != stored_coords
                or self.file_id_edit.text().strip() != (tmpl.get("file_id", ""))
                or self.token_edit.toPlainText().strip() != (u_prev.get("credentials", {}).get("token", ""))
                or self.cf_edit.toPlainText().strip() != (u_prev.get("credentials", {}).get("cf_clearance", ""))
                or current_colors != stored_colors
            )
            if changed:
                msg = QMessageBox(self)
                msg.setWindowTitle("未保存更改")
                msg.setText("当前用户存在未保存的更改，是否保存？")
                save_btn = msg.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
                cancel_btn = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
                msg.exec()
                clicked = msg.clickedButton()
                if clicked == save_btn:
                    self.users_list.blockSignals(True)
                    self.users_list.setCurrentRow(prev)
                    self.users_list.blockSignals(False)
                    ok = self.save_config()
                    if not ok:
                        self.users_list.blockSignals(True)
                        self.users_list.setCurrentRow(prev)
                        self.users_list.blockSignals(False)
                        return
                elif clicked == cancel_btn:
                    self.users_list.blockSignals(True)
                    self.users_list.setCurrentRow(prev)
                    self.users_list.blockSignals(False)
                    return

        # 重新从磁盘读取 users 以反映外部更改
        cfg = read_config()
        users: list[dict[str, Any]] = cfg.get("users", [])
        if isinstance(users, list):
            self.users = users

        if row < 0 or row >= len(self.users):
            # 无需加载
            self.last_selected_row = row
            return

        u = self.users[row]
        tmpl: dict[str, Any] = u.get("template", {})
        creds: dict[str, Any] = u.get("credentials", {})
        coords: dict[str, int] = tmpl.get("coords", {})
        tlx = coords.get("tlx")
        tly = coords.get("tly")
        pxx = coords.get("pxx")
        pxy = coords.get("pxy")
        if all(isinstance(v, int) for v in (tlx, tly, pxx, pxy)):
            coords_str = f"(Tl X: {tlx}, Tl Y: {tly}, Px X: {pxx}, Px Y: {pxy})"
            self.coords_edit.setText(coords_str)
        else:
            self.coords_edit.clear()

        self.file_id_edit.setText(tmpl.get("file_id", ""))
        self.token_edit.setPlainText(creds.get("token", ""))
        self.cf_edit.setPlainText(creds.get("cf_clearance", ""))

        # 加载颜色偏好
        self.colors_list.clear()
        preferred_colors = u.get("preferred_colors", [])
        if isinstance(preferred_colors, list):
            for color in preferred_colors:
                self.colors_list.addItem(color)

        # 如果存在每用户模板图片则加载
        if file_id := tmpl.get("file_id"):
            path = TEMPLATES_DIR / f"{file_id}.png"
            if path.is_file():
                self.img_label.set_image(str(path))
                if selected := u.get("selected_area"):
                    self.img_label.setSelectionFromOriginalRect(QRect(*selected))
                self.last_selected_row = row
                return

        # 否则清空预览
        self.img_label.setPixmap(QPixmap())
        self.img_label.setText("拖放图片到此处或点击上传")
        self.img_label.filepath = None

        # 更新上次选中行
        self.last_selected_row = row

    def add_color(self) -> None:
        """弹出对话框选择颜色添加到列表"""
        if not self.all_colors:
            QMessageBox.warning(self, "错误", "无法加载颜色列表")
            return

        # 创建颜色选择对话框
        colors_str, ok = QInputDialog.getItem(self, "选择颜色", "可用的颜色:", self.all_colors, 0, False)
        if ok and colors_str:
            self.colors_list.addItem(colors_str)

    def remove_color(self) -> None:
        """移除选中的颜色"""
        for item in self.colors_list.selectedItems():
            self.colors_list.takeItem(self.colors_list.row(item))

    def move_color_up(self) -> None:
        """将选中的颜色向上移动"""
        current_row = self.colors_list.currentRow()
        if current_row > 0:
            item = self.colors_list.takeItem(current_row)
            self.colors_list.insertItem(current_row - 1, item)
            self.colors_list.setCurrentRow(current_row - 1)

    def move_color_down(self) -> None:
        """将选中的颜色向下移动"""
        current_row = self.colors_list.currentRow()
        if current_row >= 0 and current_row < self.colors_list.count() - 1:
            item = self.colors_list.takeItem(current_row)
            self.colors_list.insertItem(current_row + 1, item)
            self.colors_list.setCurrentRow(current_row + 1)


def gui_main() -> None:
    app = QApplication(sys.argv)
    w = ConfigInitWindow()
    w.resize(900, 700)
    w.show()
    sys.exit(app.exec())
