import os
import csv
import cv2
import torch
import random
import numpy as np
from PIL import Image
from datetime import datetime
from torch import nn
from torch.utils.data import Dataset, DataLoader, random_split
from torchvision import transforms
from torch.utils.tensorboard import SummaryWriter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATASET_ROOT = os.path.join(BASE_DIR, "debug_ocr", "roi_dataset")
IMAGE_DIR = os.path.join(DATASET_ROOT, "images")
LABEL_CSV = os.path.join(DATASET_ROOT, "labels.csv")

MODEL_SAVE_PATH = os.path.join(BASE_DIR, "timestamp_crnn.pt")
BEST_MODEL_PATH = os.path.join(BASE_DIR, "timestamp_crnn_best.pt")
RUNS_DIR = os.path.join(BASE_DIR, "runs")

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

BATCH_SIZE = 16
EPOCHS = 160
LR = 1e-4

IMG_H = 64
IMG_W = 512
NUM_WORKERS = 4

# 训练格式：05-07 16:46:59
# 不要年份，不要毫秒
ALPHABET = "0123456789-: "

CHAR_TO_INDEX = {c: i + 1 for i, c in enumerate(ALPHABET)}
INDEX_TO_CHAR = {i + 1: c for i, c in enumerate(ALPHABET)}
BLANK_INDEX = 0


def normalize_label(label: str) -> str:
    label = label.strip()

    # 2026-05-07 16:46:59.170 -> 05-07 16:46:59
    if "." in label:
        label = label.split(".")[0]

    if len(label) >= 19 and label[4] == "-":
        label = label[5:]

    return label


class OCRDataset(Dataset):
    def __init__(self, image_dir, label_csv):
        self.samples = []

        with open(label_csv, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)

            for row in reader:
                if len(row) < 2:
                    continue

                image_name = row[0].strip()
                label = normalize_label(row[1])

                image_path = os.path.join(image_dir, image_name)

                if not os.path.exists(image_path):
                    continue

                if any(c not in CHAR_TO_INDEX for c in label):
                    continue

                self.samples.append((image_path, label))

        if not self.samples:
            raise RuntimeError("没有可训练数据，请检查 labels.csv 和 images")

        print(f"有效数据: {len(self.samples)} 张")
        print("示例 label:", self.samples[0][1])

        self.transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.5,), (0.5,))
        ])

    def __len__(self):
        return len(self.samples)

    def random_augment(self, img):
        if random.random() < 0.2:
            img = cv2.GaussianBlur(img, (3, 3), 0)

        if random.random() < 0.2:
            noise = np.random.normal(0, 5, img.shape).astype(np.uint8)
            img = cv2.add(img, noise)

        if random.random() < 0.3:
            alpha = random.uniform(0.9, 1.15)
            beta = random.randint(-10, 10)
            img = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)

        return img

    def __getitem__(self, idx):
        image_path, label = self.samples[idx]

        img = cv2.imread(image_path)

        if img is None:
            raise RuntimeError(f"图片读取失败: {image_path}")

        img = self.random_augment(img)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        gray = cv2.resize(
            gray,
            (IMG_W, IMG_H),
            interpolation=cv2.INTER_CUBIC
        )

        pil = Image.fromarray(gray)
        tensor = self.transform(pil)

        target = torch.LongTensor([
            CHAR_TO_INDEX[c]
            for c in label
        ])

        return tensor, target, label


def collate_fn(batch):
    images = []
    labels = []
    label_texts = []

    for img, target, text in batch:
        images.append(img)
        labels.append(target)
        label_texts.append(text)

    images = torch.stack(images)

    target_lengths = torch.LongTensor([
        len(t)
        for t in labels
    ])

    targets = torch.cat(labels)

    return images, targets, target_lengths, label_texts


class CRNN(nn.Module):
    def __init__(self, num_classes):
        super().__init__()

        self.cnn = nn.Sequential(
            nn.Conv2d(1, 64, 3, 1, 1),
            nn.BatchNorm2d(64),
            nn.ReLU(True),
            nn.MaxPool2d(2, 2),

            nn.Conv2d(64, 128, 3, 1, 1),
            nn.BatchNorm2d(128),
            nn.ReLU(True),
            nn.MaxPool2d(2, 2),

            nn.Conv2d(128, 256, 3, 1, 1),
            nn.BatchNorm2d(256),
            nn.ReLU(True),

            nn.Conv2d(256, 256, 3, 1, 1),
            nn.BatchNorm2d(256),
            nn.ReLU(True),
            nn.MaxPool2d((2, 1), (2, 1)),

            nn.Conv2d(256, 512, 3, 1, 1),
            nn.BatchNorm2d(512),
            nn.ReLU(True),

            nn.Conv2d(512, 512, 3, 1, 1),
            nn.BatchNorm2d(512),
            nn.ReLU(True),
            nn.MaxPool2d((2, 1), (2, 1)),
        )

        self.rnn = nn.LSTM(
            input_size=512 * 4,
            hidden_size=256,
            num_layers=2,
            bidirectional=True,
            batch_first=False,
        )

        self.fc = nn.Linear(512, num_classes)

    def forward(self, x):
        conv = self.cnn(x)

        b, c, h, w = conv.size()

        conv = conv.permute(3, 0, 1, 2)
        conv = conv.contiguous().view(w, b, c * h)

        recurrent, _ = self.rnn(conv)
        output = self.fc(recurrent)

        return output


def decode_prediction(pred):
    pred = pred.argmax(2)
    pred = pred[:, 0].detach().cpu().numpy().tolist()

    result = []
    last = BLANK_INDEX

    for i in pred:
        if i != BLANK_INDEX and i != last:
            result.append(INDEX_TO_CHAR.get(i, ""))

        last = i

    return "".join(result)


def calc_exact_accuracy(preds, gts):
    correct = 0

    for p, g in zip(preds, gts):
        if p == g:
            correct += 1

    return correct / max(len(gts), 1)


def run_eval(model, loader, criterion):
    model.eval()

    total_loss = 0.0
    preds_all = []
    gts_all = []

    with torch.no_grad():
        for images, targets, target_lengths, label_texts in loader:
            images = images.to(DEVICE)
            targets = targets.to(DEVICE)
            target_lengths = target_lengths.to(DEVICE)

            preds = model(images)
            log_probs = preds.log_softmax(2)

            t, n, c = log_probs.size()

            input_lengths = torch.full(
                size=(n,),
                fill_value=t,
                dtype=torch.long,
                device=DEVICE,
            )

            loss = criterion(
                log_probs,
                targets,
                input_lengths,
                target_lengths,
            )

            total_loss += loss.item()

            decoded = []

            for i in range(n):
                pred_text = decode_prediction(
                    preds[:, i:i + 1, :]
                )
                decoded.append(pred_text)

            preds_all.extend(decoded)
            gts_all.extend(label_texts)

    avg_loss = total_loss / max(len(loader), 1)
    acc = calc_exact_accuracy(preds_all, gts_all)

    examples = list(zip(gts_all[:8], preds_all[:8]))

    return avg_loss, acc, examples


def save_model(model):
    torch.save({
        "model": model.state_dict(),
        "alphabet": ALPHABET,
        "img_h": IMG_H,
        "img_w": IMG_W,
        "label_format": "MM-DD HH:MM:SS",
        "drop_year": True,
        "drop_milliseconds": True,
    }, MODEL_SAVE_PATH)


def save_best_model(model):
    torch.save({
        "model": model.state_dict(),
        "alphabet": ALPHABET,
        "img_h": IMG_H,
        "img_w": IMG_W,
        "label_format": "MM-DD HH:MM:SS",
        "drop_year": True,
        "drop_milliseconds": True,
    }, BEST_MODEL_PATH)


def main():
    print("===================================")
    print("DEVICE:", DEVICE)
    print("IMG_H:", IMG_H)
    print("IMG_W:", IMG_W)
    print("LABEL_FORMAT: MM-DD HH:MM:SS")
    print("DROP_MS: True")
    print("MODEL:", MODEL_SAVE_PATH)
    print("===================================")

    dataset = OCRDataset(IMAGE_DIR, LABEL_CSV)

    train_size = int(len(dataset) * 0.8)
    val_size = len(dataset) - train_size

    train_dataset, val_dataset = random_split(
        dataset,
        [train_size, val_size],
        generator=torch.Generator().manual_seed(42)
    )

    print(f"训练集: {len(train_dataset)}")
    print(f"验证集: {len(val_dataset)}")

    train_loader = DataLoader(
        train_dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=NUM_WORKERS,
        collate_fn=collate_fn,
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=NUM_WORKERS,
        collate_fn=collate_fn,
    )

    model = CRNN(
        num_classes=len(ALPHABET) + 1
    ).to(DEVICE)

    criterion = nn.CTCLoss(
        blank=BLANK_INDEX,
        zero_infinity=True
    )

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=LR
    )

    run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    writer = SummaryWriter(os.path.join(RUNS_DIR, run_name))

    global_step = 0
    best_val_acc = 0.0

    for epoch in range(EPOCHS):
        model.train()

        train_loss = 0.0
        train_preds = []
        train_gts = []

        for batch_idx, (
            images,
            targets,
            target_lengths,
            label_texts,
        ) in enumerate(train_loader):

            images = images.to(DEVICE)
            targets = targets.to(DEVICE)
            target_lengths = target_lengths.to(DEVICE)

            optimizer.zero_grad()

            preds = model(images)
            log_probs = preds.log_softmax(2)

            t, n, c = log_probs.size()

            input_lengths = torch.full(
                size=(n,),
                fill_value=t,
                dtype=torch.long,
                device=DEVICE,
            )

            loss = criterion(
                log_probs,
                targets,
                input_lengths,
                target_lengths,
            )

            loss.backward()
            optimizer.step()

            train_loss += loss.item()

            decoded = []

            for i in range(n):
                pred_text = decode_prediction(
                    preds[:, i:i + 1, :]
                )
                decoded.append(pred_text)

            train_preds.extend(decoded)
            train_gts.extend(label_texts)

            step_acc = calc_exact_accuracy(decoded, label_texts)

            writer.add_scalar("Loss/train_step", loss.item(), global_step)
            writer.add_scalar("Accuracy/train_step", step_acc, global_step)

            if global_step % 50 == 0:
                print()
                print("=" * 80)
                print(f"Epoch: {epoch}")
                print(f"Step : {global_step}")
                print(f"Loss : {loss.item():.4f}")
                print(f"Acc  : {step_acc:.4f}")
                print("GT  :", label_texts[0])
                print("PRED:", decoded[0])
                print("=" * 80)

                img = images[0].detach().cpu().squeeze(0).numpy()
                img = ((img * 0.5) + 0.5) * 255
                img = img.astype(np.uint8)

                writer.add_image(
                    "Realtime/Input_Image",
                    img,
                    global_step,
                    dataformats="HW",
                )

                writer.add_text(
                    "Realtime/GT_PRED",
                    f"GT: {label_texts[0]}\nPRED: {decoded[0]}",
                    global_step,
                )

            global_step += 1

        avg_train_loss = train_loss / max(len(train_loader), 1)
        train_acc = calc_exact_accuracy(train_preds, train_gts)

        val_loss, val_acc, val_examples = run_eval(
            model,
            val_loader,
            criterion,
        )

        writer.add_scalar("Loss/train_epoch", avg_train_loss, epoch)
        writer.add_scalar("Loss/val_epoch", val_loss, epoch)
        writer.add_scalar("Accuracy/train_exact", train_acc, epoch)
        writer.add_scalar("Accuracy/val_exact", val_acc, epoch)

        print()
        print("#" * 80)
        print(f"Epoch {epoch} 完成")
        print(f"Train Loss: {avg_train_loss:.4f}")
        print(f"Train Accuracy: {train_acc:.4f}")
        print(f"Val Loss: {val_loss:.4f}")
        print(f"Val Accuracy: {val_acc:.4f}")
        print("验证集样例:")
        for gt, pred in val_examples:
            print("GT  :", gt)
            print("PRED:", pred)
            print("-" * 40)
        print("#" * 80)

        save_model(model)

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            save_best_model(model)
            print("保存最佳模型:", BEST_MODEL_PATH)

    writer.close()

    print()
    print("训练完成")
    print("最终模型:", MODEL_SAVE_PATH)
    print("最佳模型:", BEST_MODEL_PATH)
    print("最佳 Val Accuracy:", best_val_acc)


if __name__ == "__main__":
    main()