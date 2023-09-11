import os
from collections import Counter

import datasets
from datasets import DatasetDict, load_dataset

from src.dataset_module import CocoDataset


def get_caption_prompt(single_caption=None) -> str:
    return f"<image>Output:{single_caption if single_caption is not None else ''}{'<|endofchunk|>' if single_caption is not None else ''}"


def get_vqa_prompt(question, answer=None) -> str:
    return f"<image>Question:{question} Short answer:{answer if answer is not None else ''}{'<|endofchunk|>' if answer is not None else ''}"


def load_coco_ds(cfg, split=None):
    if cfg.dataset.name == 'coco_karpathy_split':
        # TODO: 完善load batch的方法
        ds = load_karpathy_split(cfg, split)
    else:
        if split is None:
            train_ds = CocoDataset(
                cfg.dataset.train_coco_dataset_root,
                cfg.dataset.train_coco_annotation_file,
            )
            val_ds = CocoDataset(
                cfg.dataset.val_coco_dataset_root, cfg.dataset.val_coco_annotation_file
            )
            train_ds = datasets.Dataset.from_list(train_ds)
            val_ds = datasets.Dataset.from_list(val_ds)
            ds = DatasetDict({'train': train_ds, 'validation': val_ds})
            ds = ds.sort('image_id')
            ds = ds.cast_column('image', datasets.Image(decode=True))
        else:
            if split == 'train':
                ds = CocoDataset(
                    cfg.dataset.train_coco_dataset_root,
                    cfg.dataset.train_coco_annotation_file,
                )
            elif split == 'validation':
                ds = CocoDataset(
                    cfg.dataset.val_coco_dataset_root,
                    cfg.dataset.val_coco_annotation_file,
                )
            ds = datasets.Dataset.from_list(ds)
            ds = ds.sort('image_id')
            ds = ds.cast_column('image', datasets.Image(decode=True))
    return ds


def load_vqav2_ds(cfg, split=None):
    if cfg.dataset.version == 'local':
        data_files = {
            'train': cfg.dataset.train_path,
            'validation': cfg.dataset.val_path,
        }
        ds = load_dataset(
            'json', data_files=data_files, field='annotations', split=split
        )
        ds = ds.sort('question_id')

        def train_trans(x, idx):
            filename = [f"COCO_train2014_{idx:012d}.jpg" for idx in x['image_id']]
            img_path = [
                os.path.join(cfg.dataset.train_coco_dataset_root, f_n)
                for f_n in filename
            ]

            x['image'] = img_path
            x['idx'] = idx
            return x

        def val_trans(x, idx):
            filename = [f"COCO_val2014_{idx:012d}.jpg" for idx in x['image_id']]
            img_path = [
                os.path.join(cfg.dataset.val_coco_dataset_root, f_n) for f_n in filename
            ]
            x['image'] = img_path
            x['idx'] = idx
            return x

        if split is None:
            ds['train'] = ds['train'].map(
                train_trans, batched=True, with_indices=True, num_proc=12
            )
            ds['validation'] = ds['validation'].map(
                val_trans, batched=True, with_indices=True, num_proc=12
            )
        elif split == 'train':
            ds = ds.map(train_trans, batched=True, with_indices=True, num_proc=12)
        elif split == 'validation':
            ds = ds.map(val_trans, batched=True, with_indices=True, num_proc=12)
        ds = ds.cast_column('image', datasets.Image(decode=True))
    elif cfg.dataset.version == 'hub':
        ds = load_dataset('HuggingFaceM4/VQAv2', split=split)
        ds.pop('test', None)
        ds.pop('testdev', None)
        ds = ds.sort('question_id')

    def gene_answer_for_batch(batch_data):
        answers = [gene_answer(answers) for answers in batch_data['answers']]
        questions = [q for q in batch_data['question']]
        q_a = [
            f'Question:{q} Answer: {a}' for q, a in zip(questions, answers)
        ]
        batch_data['answer'] = answers
        batch_data['q_a'] = q_a
        return batch_data

    def gene_answer(data):
        # Use list comprehension to filter out answers with answer_confidence = "yes"
        yes_answers = [
            item['answer'] for item in data if item['answer_confidence'] == 'yes'
        ]

        # Use Counter to count the occurrences of each answer
        answer_counts = Counter(yes_answers)

        # Find the most common answer
        most_common_answer = answer_counts.most_common(1)

        if most_common_answer:
            return most_common_answer[0][0]

        maybe_answers = [
            item['answer'] for item in data if item['answer_confidence'] == 'maybe'
        ]
        answer_counts = Counter(maybe_answers)
        most_common_answer = answer_counts.most_common(1)
        if most_common_answer:
            return most_common_answer[0][0]
        return data[0]['answer']

    ds = ds.map(gene_answer_for_batch, batched=True, num_proc=12)
    return ds


def load_karpathy_split(cfg, split=None):
    ds = load_dataset(cfg.dataset.karpathy_path, split=split)
    if split is None:
        ds.pop('validation', None)
        ds.pop('restval', None)
        ds['validation'] = ds['test']
        ds.pop('test', None)

    ds = ds.sort("cocoid")

    ds = ds.rename_columns({'sentences': 'captions', 'cocoid': 'image_id'})

    def transform(example, idx):
        example['single_caption'] = [e[0] for e in example['captions']]
        if 'train' in example['filepath']:
            coco_dir = cfg.dataset.train_coco_dataset_root
        elif 'val' in example['filepath']:
            coco_dir = cfg.dataset.val_coco_dataset_root

        example['image'] = os.path.join(coco_dir, example['filename'])
        example['idx'] = idx
        return example

    ds = ds.map(
        transform,
        with_indices=True,
        remove_columns=['sentids', 'imgid', 'filename', 'split'],
        batched=True,
        num_proc=12,
    )
    ds = ds.cast_column('image', datasets.Image(decode=True))
    return ds
