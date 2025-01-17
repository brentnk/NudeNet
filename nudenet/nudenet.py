import os
import math
import cv2
import numpy as np
import onnxruntime
from onnxruntime.capi import _pybind_state as C
import requests
from tempfile import NamedTemporaryFile
import glob
import tqdm


__labels = [
    "FEMALE_GENITALIA_COVERED",
    "FACE_FEMALE",
    "BUTTOCKS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_BREAST_EXPOSED",
    "ANUS_EXPOSED",
    "FEET_EXPOSED",
    "BELLY_COVERED",
    "FEET_COVERED",
    "ARMPITS_COVERED",
    "ARMPITS_EXPOSED",
    "FACE_MALE",
    "BELLY_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_COVERED",
    "FEMALE_BREAST_COVERED",
    "BUTTOCKS_COVERED",
]


__labels_explicit = [
    "ANUS_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_BREAST_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
]


def _read_image(image_path, target_size=320):
    img = cv2.imread(image_path)
    img_height, img_width = img.shape[:2]
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    aspect = img_width / img_height

    if img_height > img_width:
        new_height = target_size
        new_width = int(round(target_size * aspect))
    else:
        new_width = target_size
        new_height = int(round(target_size / aspect))

    resize_factor = math.sqrt(
        (img_width**2 + img_height**2) / (new_width**2 + new_height**2)
    )

    img = cv2.resize(img, (new_width, new_height),
                     interpolation=cv2.INTER_LINEAR)

    pad_x = target_size - new_width
    pad_y = target_size - new_height

    pad_top, pad_bottom = [int(i) for i in np.floor([pad_y, pad_y]) / 2]
    pad_left, pad_right = [int(i) for i in np.floor([pad_x, pad_x]) / 2]

    img = cv2.copyMakeBorder(
        img,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=[0, 0, 0],
    )

    img = cv2.resize(img, (target_size, target_size))

    image_data = img.astype("float32") / 255.0  # normalize
    image_data = np.transpose(image_data, (2, 0, 1))
    image_data = np.expand_dims(image_data, axis=0)

    return image_data, resize_factor, pad_left, pad_top


def _postprocess(output, resize_factor, pad_left, pad_top):
    outputs = np.transpose(np.squeeze(output[0]))
    rows = outputs.shape[0]
    boxes = []
    scores = []
    class_ids = []

    for i in range(rows):
        classes_scores = outputs[i][4:]
        max_score = np.amax(classes_scores)

        if max_score >= 0.2:
            class_id = np.argmax(classes_scores)
            x, y, w, h = outputs[i][0], outputs[i][1], outputs[i][2], outputs[i][3]
            left = int(round((x - w * 0.5 - pad_left) * resize_factor))
            top = int(round((y - h * 0.5 - pad_top) * resize_factor))
            width = int(round(w * resize_factor))
            height = int(round(h * resize_factor))
            class_ids.append(class_id)
            scores.append(max_score)
            boxes.append([left, top, width, height])

    indices = cv2.dnn.NMSBoxes(boxes, scores, 0.25, 0.45)

    detections = []
    for i in indices:
        box = boxes[i]
        score = scores[i]
        class_id = class_ids[i]
        detections.append(
            {"class": __labels[class_id], "score": float(score), "box": box}
        )

    return detections


class NudeDetector:
    def __init__(self, providers=None):
        self.onnx_session = onnxruntime.InferenceSession(
            os.path.join(os.path.dirname(__file__), "best.onnx"),
            providers=C.get_available_providers() if not providers else providers,
        )
        model_inputs = self.onnx_session.get_inputs()
        input_shape = model_inputs[0].shape
        self.input_width = input_shape[2]  # 320
        self.input_height = input_shape[3]  # 320
        self.input_name = model_inputs[0].name

    def detect(self, image_path):

        # if the image is a url, download it and save it locally to a temp folder
        if image_path.startswith("http"):

            response = requests.get(image_path)
            img = NamedTemporaryFile(delete=False)
            img.write(response.content)
            img.close()
            image_path = img.name
            print(f'Image downloaded to {image_path}')

        preprocessed_image, resize_factor, pad_left, pad_top = _read_image(
            image_path, self.input_width
        )
        outputs = self.onnx_session.run(
            None, {self.input_name: preprocessed_image})
        detections = _postprocess(outputs, resize_factor, pad_left, pad_top)

        return detections

    # -> str | Any:
    def censor(self, image_path, classes=[], output_path=None):
        detections = self.detect(image_path)
        if classes:
            detections = [
                detection for detection in detections if detection["class"] in classes
            ]

        if not detections:
            return None

        img = cv2.imread(image_path)

        for detection in detections:
            box = detection["box"]
            x, y, w, h = box[0], box[1], box[2], box[3]
            # change these pixels to pure black
            # img[y: y + h, x: x + w] = (0, 0, 0)
            # draw a red rectangle around the detected object
            cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 2)
            # add the label and confidence score
            text = f"{detection['class']} {detection['score']:.2f}"
            cv2.putText(
                img,
                text,
                (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                2,
            )

        if not output_path:
            image_path, ext = os.path.splitext(image_path)
            output_path = f"{image_path}_censored{ext}"

        cv2.imwrite(output_path, img)

        return output_path


def main():
    detector = NudeDetector()

    # images = glob.glob(
    #     "/Users/brentnk/Documents/dataset/community_lib/*.jpg")
    images = glob.glob(
        "/Users/brentnk/Documents/dataset/scan-bad/bad/*.jpg")[:50]
    print(f"Found {len(images)} images")

    output_dir = os.path.join('tmp', 'images')
    print(f"saving censor images to {output_dir}")

    # iterate over all files in a directory
    pbar = tqdm.tqdm(images)
    for filename in pbar:
        pbar.set_description(f"Processing {filename}")
        detector.censor(
            filename,
            __labels_explicit,
            os.path.join(
                output_dir, f"censored_{os.path.basename(filename)}.jpg"),
        )

    # detections = detector.detect(
    #     "/var/folders/0h/zfs6xc_s7vjbnyrh3d8sqypw0000gn/T/tmp3l2wxm4_")
    # print(f'detections:\n{detections}')
    # detector.censor("/Users/brentnk/Documents/dataset/community_lib/1701016874194_tl_dBnEhk5c6.jpg",
    #                 __labels, None)


if __name__ == "__main__":
    main()
