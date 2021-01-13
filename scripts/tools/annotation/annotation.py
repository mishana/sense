#!/usr/bin/env python
"""
The annotation script allows you to annotate the frames generated by `prepare_annotation.py` for a given class and
split in the data-set folder.
"""


import datetime
import glob
import json
import numpy as np
import os

from flask import Flask
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import send_from_directory
from flask import url_for
from joblib import dump
from joblib import load
from os.path import join
from sklearn.linear_model import LogisticRegression

from sense.finetuning import compute_frames_features


app = Flask(__name__)
app.secret_key = 'd66HR8dç"f_-àgjYYic*dh'

MODULE_DIR = os.path.dirname(__file__)
PROJECTS_OVERVIEW_CONFIG_FILE = os.path.join(MODULE_DIR, 'projects_config.json')

PROJECT_CONFIG_FILE = 'project_config.json'


def _load_feature_extractor():
    global inference_engine
    import torch
    from sense import engine
    from sense import feature_extractors
    if inference_engine is None:
        feature_extractor = feature_extractors.StridedInflatedEfficientNet()

        # Remove internal padding for feature extraction and training
        checkpoint = torch.load('resources/backbone/strided_inflated_efficientnet.ckpt')
        feature_extractor.load_state_dict(checkpoint)
        feature_extractor.eval()

        # Create Inference Engine
        inference_engine = engine.InferenceEngine(feature_extractor, use_gpu=True)


def _extension_ok(filename):
    """ Returns `True` if the file has a valid image extension. """
    return '.' in filename and filename.rsplit('.', 1)[1] in ('png', 'jpg', 'jpeg', 'gif', 'bmp')


def _load_project_config():
    if os.path.isfile(PROJECTS_OVERVIEW_CONFIG_FILE):
        with open(PROJECTS_OVERVIEW_CONFIG_FILE, 'r') as f:
            projects = json.load(f)
        return projects
    else:
        projects = []
        with open(PROJECTS_OVERVIEW_CONFIG_FILE, 'w') as f:
            json.dump(projects, f, indent=2)
        return projects


@app.route('/')
def projects_overview():
    """TODO"""
    # TODO: Check if listed projects are still valid
    return render_template('up_projects_overview.html', projects=_load_project_config())


@app.route('/new-project-setup')
def new_project_setup():
    """TODO"""
    return render_template('up_new_project_setup.html')


@app.route('/check-existing-project', methods=['POST'])
def check_existing_project():
    """TODO"""
    data = request.json
    path = data['path']

    subdirs = [d for d in glob.glob(f'{path}*') if os.path.isdir(d)]

    if not os.path.exists(path):
        return jsonify(path_exists=False, classes=[], subdirs=subdirs)

    train_dir = os.path.join(path, 'videos_train')
    classes = []
    if os.path.exists(train_dir):
        classes = os.listdir(train_dir)

    return jsonify(path_exists=True, classes=classes, subdirs=subdirs)


@app.route('/create-new-project', methods=['POST'])
def create_new_project():
    """TODO"""
    data = request.form
    name = data['name']
    path = data['path']

    classes = {}
    class_idx = 0
    class_key = f'class{class_idx}'
    while class_key in data:
        class_name = data[class_key]
        if class_name:
            classes[class_name] = [
                data[f'{class_key}_tag{tag_idx}'] or f'{class_name}_{tag_idx}'
                for tag_idx in range(1, 3)
            ]

        class_idx += 1
        class_key = f'class{class_idx}'

    config = {
        'name': name,
        'date_created': datetime.date.today().isoformat(),
        'classes': classes,
    }

    # Initialize config file in project directory
    if not os.path.exists(path):
        os.mkdir(path)

    config_file = os.path.join(path, PROJECT_CONFIG_FILE)
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    # Setup directory structure
    for split in ['train', 'valid']:
        videos_dir = os.path.join(path, f'videos_{split}')
        if not os.path.exists(videos_dir):
            print(f'Creating {videos_dir}')
            os.mkdir(videos_dir)

        for class_name in classes:
            class_dir = os.path.join(videos_dir, class_name)

            if not os.path.exists(class_dir):
                print(f'Creating {class_dir}')
                os.mkdir(class_dir)

    # Update overall projects config file
    projects = _load_project_config()
    projects.append({
        'name': name,
        'path': path,
    })
    with open(PROJECTS_OVERVIEW_CONFIG_FILE, 'w') as f:
        json.dump(projects, f, indent=2)

    return redirect(url_for('project_details', path=path))


@app.route('/project/<path:path>')
def project_details(path):
    """TODO"""
    path = f'/{path}'  # Make path absolute
    config_file = os.path.join(path, PROJECT_CONFIG_FILE)

    with open(config_file) as f:
        config = json.load(f)

    stats = {}
    for class_name, tags in config['classes'].items():
        stats[class_name] = {}
        for split in ['train', 'valid']:
            videos_path = os.path.join(path, f'videos_{split}', class_name)
            tags_path = os.path.join(path, f'tags_{split}', class_name)
            stats[class_name][split] = {
                'total': len(os.listdir(videos_path)),
                'tagged': len(os.listdir(tags_path)) if os.path.exists(tags_path) else 0,
            }

    return render_template('up_project_details.html', config=config, path=path, stats=stats)


@app.route('/annotate/<split>/<label>/<path:path>')
def show_video_list(split, label, path):
    """Gets the data and creates the HTML template with all videos for the given class-label."""
    path = f'/{path}'  # Make path absolute
    frames_dir = join(path, f"frames_{split}", label)
    tags_dir = join(path, f"tags_{split}", label)
    logreg_dir = join(path, 'logreg', label)

    os.makedirs(logreg_dir, exist_ok=True)
    os.makedirs(tags_dir, exist_ok=True)

    # load feature extractor if needed
    _load_feature_extractor()
    # compute the features and frames missing.
    compute_frames_features(inference_engine, split, label, path)

    videos = os.listdir(frames_dir)
    videos.sort()

    logreg_path = join(logreg_dir, 'logreg.joblib')
    if os.path.isfile(logreg_path):
        global logreg
        logreg = load(logreg_path)

    folder_id = zip(videos, list(range(len(videos))))
    return render_template('up_folder.html', folders=folder_id, split=split, label=label, path=path)


@app.route('/prepare_annotation/<path:path>')
def prepare_annotation(path):
    """Gets the data and creates the HTML template with all videos for the given class-label."""
    dataset_path = f'/{path}'  # Make path absolute

    # load feature extractor if needed
    _load_feature_extractor()
    for split in ['train', 'valid']:
        print("\n" + "-" * 10 + f"Preparing videos in the {split}-set" + "-" * 10)
        for label in os.listdir(join(dataset_path, f'videos_{split}')):
            compute_frames_features(inference_engine, split, label, dataset_path)
    return redirect(url_for("project_details", path=path))


@app.route('/annotate/<split>/<label>/<path:path>/<int:idx>')
def annotate(split, label, path, idx):
    """For the given class-label, this shows all the frames for annotating the selected video."""
    path = f'/{path}'  # Make path absolute
    frames_dir = join(path, f"frames_{split}", label)
    features_dir = join(path, f"features_{split}", label)

    videos = os.listdir(frames_dir)
    videos.sort()

    features = np.load(join(features_dir, videos[idx] + ".npy"))
    features = features.mean(axis=(2, 3))

    if logreg is not None:
        classes = list(logreg.predict(features))
    else:
        classes = [0] * len(features)

    # The list of images in the folder
    images = [image for image in glob.glob(join(frames_dir, videos[idx] + '/*'))
              if _extension_ok(image)]

    indexes = [int(image.split('.')[0].split('/')[-1]) for image in images]
    n_images = len(indexes)

    images = [[image, idx] for idx, image in sorted(zip(indexes, images))]
    images = [[image, idx, _class] for (image, idx), _class in zip(images, classes)]

    chunk_size = 5
    images = np.array_split(images, np.arange(chunk_size, len(images), chunk_size))
    images = [list(image) for image in images]

    return render_template('up_list.html', images=images, idx=idx, fps=16,
                           n_images=n_images, video_name=videos[idx],
                           split=split, label=label, path=path)


@app.route('/response', methods=['POST'])
def response():
    if request.method == 'POST':
        data = request.form  # a multi-dict containing POST data
        print(data)
        idx = int(data['idx'])
        fps = float(data['fps'])
        path = data['path']
        split = data['split']
        label = data['label']
        video = data['video']
        next_frame_idx = idx + 1

        tags_dir = join(path, f"tags_{split}", label)
        frames_dir = join(path, f"frames_{split}", label)
        description = {'file': video + ".mp4", 'fps': fps}

        out_annotation = os.path.join(tags_dir, video + ".json")
        time_annotation = []

        for i in range(int(data['n_images'])):
            time_annotation.append(int(data[str(i)]))

        description['time_annotation'] = time_annotation
        json.dump(description, open(out_annotation, 'w'))

        if next_frame_idx >= len(os.listdir(frames_dir)):
            return redirect(url_for('project_details', path=path))

    return redirect(url_for('annotate', split=split, label=label, path=path, idx=next_frame_idx))


@app.route('/train_logreg', methods=['POST'])
def train_logreg():
    global logreg

    if request.method == 'POST':
        data = request.form  # a multi-dict containing POST data
        idx = int(data['idx'])
        path = data['path']
        split = data['split']
        label = data['label']

        tags_dir = join(path, f"tags_{split}", label)
        features_dir = join(path, f"features_{split}", label)
        logreg_dir = join(path, 'logreg', label)
        logreg_path = join(logreg_dir, 'logreg.joblib')

        annotations = os.listdir(tags_dir)
        class_weight = {0: 0.5}

        if annotations:
            features = [join(features_dir, x.replace('.json', '.npy')) for x in annotations]
            annotations = [join(tags_dir, x) for x in annotations]
            X = []
            y = []

            for feature in features:
                feature = np.load(feature)

                for f in feature:
                    X.append(f.mean(axis=(1, 2)))

            for annotation in annotations:
                annotation = json.load(open(annotation, 'r'))['time_annotation']
                pos1 = np.where(np.array(annotation).astype(int) == 1)[0]

                if len(pos1) > 0:
                    class_weight.update({1: 2})

                    for p in pos1:
                        if p + 1 < len(annotation):
                            annotation[p + 1] = 1

                pos1 = np.where(np.array(annotation).astype(int) == 2)[0]

                if len(pos1) > 0:
                    class_weight.update({2: 2})

                    for p in pos1:
                        if p + 1 < len(annotation):
                            annotation[p + 1] = 2

                for a in annotation:
                    y.append(a)

            X = np.array(X)
            y = np.array(y)
            logreg = LogisticRegression(C=0.1, class_weight=class_weight)
            logreg.fit(X, y)
            dump(logreg, logreg_path)

    return redirect(url_for('annotate', split=split, label=label, path=path, idx=idx))


@app.after_request
def add_header(r):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 10 minutes.
    """
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    r.headers['Cache-Control'] = 'public, max-age=0'
    return r


@app.route('/uploads/<path:img_path>')
def download_file(img_path):
    img_path = f'/{img_path}'  # Make path absolute
    img_dir, img = os.path.split(img_path)
    return send_from_directory(img_dir, img, as_attachment=True)


if __name__ == '__main__':
    logreg = None
    inference_engine = None

    app.run(debug=True)
