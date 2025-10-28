import json
import os
import shutil
import sys
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QPushButton,
    QListWidget,
    QInputDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
    QMessageBox,
)
from app.utils import WplacePixelCoords


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
TEMPLATE_PATH = os.path.join(DATA_DIR, "template.png")


class ImageDropLabel(QLabel):
    """接受图片拖放并显示预览的 QLabel。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("拖放图片到此处或点击上传")
        self.setStyleSheet("border: 2px dashed #aaa; padding: 10px;")
        self.setAcceptDrops(True)
        self.filepath = None
    def dragEnterEvent(self,a0: Optional[QDragEnterEvent]) -> None:
        if a0 is None:
            return
        md = a0.mimeData()
        if md is not None and md.hasUrls():
            a0.acceptProposedAction()

    def dropEvent(self, a0: Optional[QDropEvent]) -> None:
        if a0 is None:
            return
        md = a0.mimeData()
        if md is None:
            return
        urls = md.urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if os.path.isfile(path):
            self.set_image(path)

    def set_image(self, path: str) -> None:
        pix = QPixmap(path)
        if pix.isNull():
            self.setText("无法打开该图片")
            self.filepath = None
            return
        self.filepath = path
        self.setPixmap(pix.scaled(320, 240, Qt.AspectRatioMode.KeepAspectRatio))


class ConfigInitWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("初始化 config.json")

        ico_path = os.path.join(DATA_DIR, "gui.ico")
        if os.path.isfile(ico_path):
            try:
                self.setWindowIcon(QIcon(ico_path))
            except Exception:
                pass

    # 坐标：单行输入 Blue Marble 格式
        self.coords_edit = QLineEdit()
        self.coords_edit.setPlaceholderText("(Tl X: 12, Tl Y: 34, Px X: 56, Px Y: 78)")

        coords_layout = QHBoxLayout()
        coords_layout.addWidget(QLabel("模板坐标:"))
        coords_layout.addWidget(self.coords_edit)

    # 用户列表与控件
        self.users_list = QListWidget()
        add_user_btn = QPushButton("新增用户")
        add_user_btn.clicked.connect(self.add_user)
        remove_user_btn = QPushButton("删除用户")
        remove_user_btn.clicked.connect(self.remove_user)

        users_h = QHBoxLayout()
        users_h.addWidget(self.users_list)
        users_ctrl_v = QVBoxLayout()
        users_ctrl_v.addWidget(add_user_btn)
        users_ctrl_v.addWidget(remove_user_btn)
        users_h.addLayout(users_ctrl_v)

        self.users_list.currentRowChanged.connect(self.on_user_selected)

    # file_id 输入（template.file_id）
        self.file_id_edit = QLineEdit()
        self.file_id_edit.setPlaceholderText("template file_id (will save as data/templates/{file_id}.png)")

    # Credentials
        self.token_edit = QTextEdit()
        self.token_edit.setPlaceholderText("token")
        self.cf_edit = QTextEdit()
        self.cf_edit.setPlaceholderText("cf_clearance")

        # Browser choice
        self.browser_cb = QComboBox()
        self.browser_cb.addItems(["chromium", "firefox", "webkit"])

        # Image drop area (per-user preview)
        self.img_label = ImageDropLabel()
        upload_btn = QPushButton("选择图片...")
        upload_btn.clicked.connect(self.choose_image)

        # Save button
        save_btn = QPushButton("保存 config.json")
        save_btn.clicked.connect(self.save_config)

        # Layout
        main = QVBoxLayout()
        main.addWidget(QLabel("用户列表"))
        main.addLayout(users_h)
        main.addWidget(QLabel("模板坐标 (coords)"))
        main.addLayout(coords_layout)
        main.addWidget(self.coords_edit)  # keep coords above
        main.addWidget(QLabel("模板图片名字"))
        main.addWidget(self.file_id_edit)
        main.addWidget(QLabel("token: wplace Cookies 中的 j (token)"))
        main.addWidget(self.token_edit)
        main.addWidget(QLabel("cf_clearance: wplace Cookies 中的 cf_clearance"))
        main.addWidget(self.cf_edit)
        main.addWidget(QLabel("浏览器选择 (全局)"))
        main.addWidget(self.browser_cb)
        main.addWidget(QLabel("模板图片预览"))
        main.addWidget(self.img_label)
        h2 = QHBoxLayout()
        h2.addWidget(upload_btn)
        h2.addWidget(save_btn)
        main.addLayout(h2)

        self.setLayout(main)

        self.users = []

        self.load_config()
        self.last_selected_row = self.users_list.currentRow() if self.users_list.count() > 0 else -1

    def choose_image(self):
        fp, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if fp:
            self.img_label.set_image(fp)

    def load_config(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
        except Exception:
            pass

        if not os.path.isfile(CONFIG_PATH):
            return

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return

        users = cfg.get("users")
        if isinstance(users, list):
            self.users = users
            self.users_list.clear()
            for u in self.users:
                self.users_list.addItem(u.get("identifier", ""))
            if self.users_list.count() > 0:
                self.users_list.setCurrentRow(0)
        else:
            tmpl = cfg.get("template")
            creds = cfg.get("credentials")
            identifier = cfg.get("identifier", "default")
            if tmpl:
                u = {"identifier": identifier, "template": tmpl, "credentials": creds or {}}
                self.users = [u]
                self.users_list.clear()
                self.users_list.addItem(identifier)
                self.users_list.setCurrentRow(0)

        browser = cfg.get("browser")
        if browser:
            idx = self.browser_cb.findText(browser)
            if idx != -1:
                self.browser_cb.setCurrentIndex(idx)

    def save_config(self):
        # 保存当前选中用户的数据到 self.users 并写回 config.json
        row = self.users_list.currentRow()
        if row < 0 or row >= len(self.users):
            QMessageBox.warning(self, "未选中用户", "请先在用户列表中选择或新增一个用户")
            return

        # parse coords
        coords_text = self.coords_edit.text().strip()
        try:
            coords = WplacePixelCoords.parse(coords_text)
        except Exception:
            QMessageBox.warning(self, "坐标解析失败", "无法解析模板坐标，请使用类似 '(Tl X: 1719, Tl Y: 855, Px X: 320, Px Y: 24)' 的格式")
            return

        file_id = self.file_id_edit.text().strip()
        if not file_id:
            QMessageBox.warning(self, "缺少 file_id", "请填写 template.file_id（用于保存为 data/templates/{file_id}.png）")
            return

        templates_dir = os.path.join(DATA_DIR, "templates")
        try:
            os.makedirs(templates_dir, exist_ok=True)
        except Exception:
            pass

        fp = getattr(self.img_label, "filepath", None)
        if isinstance(fp, str) and fp:
            dest = os.path.join(templates_dir, f"{file_id}.png")
            if os.path.exists(dest):
                pass
            else:
                try:
                    shutil.copy2(fp, dest)
                except Exception as e:
                    QMessageBox.warning(self, "保存图片失败", f"无法保存图片: {e}")

        user = self.users[row]
        user.setdefault("template", {})
        user["template"]["file_id"] = file_id
        user["template"]["coords"] = {
            "tlx": int(coords.tlx),
            "tly": int(coords.tly),
            "pxx": int(coords.pxx),
            "pxy": int(coords.pxy),
        }
        user["credentials"] = {
            "token": self.token_edit.toPlainText().strip(),
            "cf_clearance": self.cf_edit.toPlainText().strip(),
        }

        cfg = {"users": self.users, "browser": self.browser_cb.currentText()}

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"写入配置失败: {e}")
            return False

        QMessageBox.information(self, "保存成功", f"配置已保存到:\n{CONFIG_PATH}\n模板图片目录: {templates_dir}")
        # 更新用户列表显示
        user_name = self.users_list.item(row)
        if user_name:
            user_name.setText(user.get("identifier", ""))
        return True

    def write_config_to_disk(self) -> bool:
        cfg = {"users": self.users, "browser": self.browser_cb.currentText()}
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            QMessageBox.critical(self, "写入失败", f"写入配置失败: {e}")
            return False

    def add_user(self):
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
        user = {"identifier": identifier, "template": {"file_id": "", "coords": {"tlx": 0, "tly": 0, "pxx": 0, "pxy": 0}}, "credentials": {"token": "", "cf_clearance": ""}}
        self.users.append(user)
        self.users_list.addItem(identifier)
        if not self.write_config_to_disk():
            self.users.pop()
            self.users_list.takeItem(self.users_list.count() - 1)
            return
        self.users_list.setCurrentRow(self.users_list.count() - 1)

    def remove_user(self):
        row = self.users_list.currentRow()
        if row < 0 or row >= len(self.users):
            return
        identifier = self.users[row].get("identifier", "")
        ret = QMessageBox.question(self, "删除用户", f"确定删除 identifier='{identifier}' 的所有用户记录？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            if os.path.isfile(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            else:
                cfg = {"users": self.users}
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"读取配置文件失败: {e}")
            return

        users_on_disk = cfg.get("users", []) if isinstance(cfg.get("users", []), list) else []
        new_users = [u for u in users_on_disk if u.get("identifier") != identifier]

        if len(new_users) == len(users_on_disk):
            self.users = [u for u in self.users if u.get("identifier") != identifier]
        else:
            cfg["users"] = new_users
            try:
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
            except Exception as e:
                QMessageBox.critical(self, "写入失败", f"写入配置失败: {e}")
                return
            # 更新内存用户列表
            self.users = new_users

        # 刷新用户列表
        self.users_list.clear()
        for u in self.users:
            self.users_list.addItem(u.get("identifier", ""))

        # 清空输入框
        self.coords_edit.clear()
        self.file_id_edit.clear()
        self.token_edit.clear()
        self.cf_edit.clear()
        self.img_label.setText("拖放图片到此处或点击上传")
        self.img_label.filepath = None

        QMessageBox.information(self, "删除完成", f"所有 identifier='{identifier}' 的记录已删除（若存在）")

    def on_user_selected(self, row: int):
        # 处理用户选择
        prev = getattr(self, "last_selected_row", -1)
        if prev != -1 and prev != row:
            if prev < len(self.users):
                u_prev = self.users[prev]
                tmpl = u_prev.get("template", {})
                coords = tmpl.get("coords", {})
                tlx = coords.get("tlx")
                tly = coords.get("tly")
                pxx = coords.get("pxx")
                pxy = coords.get("pxy")
                stored_coords = f"(Tl X: {tlx}, Tl Y: {tly}, Px X: {pxx}, Px Y: {pxy})" if all(isinstance(v, int) for v in (tlx, tly, pxx, pxy)) else ""
                changed = (
                    self.coords_edit.text().strip() != stored_coords
                    or self.file_id_edit.text().strip() != (tmpl.get("file_id", ""))
                    or self.token_edit.toPlainText().strip() != (u_prev.get("credentials", {}).get("token", ""))
                    or self.cf_edit.toPlainText().strip() != (u_prev.get("credentials", {}).get("cf_clearance", ""))
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
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            users = cfg.get("users")
            if isinstance(users, list):
                self.users = users
        except Exception:
            pass

        if row < 0 or row >= len(self.users):
            self.last_selected_row = row
            return

        u = self.users[row]
        tmpl = u.get("template", {})
        creds = u.get("credentials", {})
        coords = tmpl.get("coords", {})
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

        file_id = tmpl.get("file_id")
        if file_id:
            path = os.path.join(DATA_DIR, "templates", f"{file_id}.png")
            if os.path.isfile(path):
                self.img_label.set_image(path)
                return

        self.img_label.setPixmap(QPixmap())
        self.img_label.setText("拖放图片到此处或点击上传")
        self.img_label.filepath = None

        self.last_selected_row = row


def main():
    app = QApplication(sys.argv)
    w = ConfigInitWindow()
    w.resize(640, 700)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
