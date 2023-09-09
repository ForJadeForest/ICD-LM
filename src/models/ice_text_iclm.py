import torch
from torch import nn
from transformers import CLIPTextModelWithProjection

from .base_iclm import BaseICLM


class ICETextICLM(BaseICLM):
    def __init__(
        self, lm_config, index_ds_size, clip_name="openai/clip-vit-base-patch32"
    ):
        super().__init__(lm_config, index_ds_size, clip_name)
        self.sen_model = CLIPTextModelWithProjection.from_pretrained(clip_name)

    def forward(self, img_input, ice_input, ice_seq_idx):
        """_summary_

        Args:
            img_input (tensor): batch_size *&
            ice_input (_type_): _description_ batchsize, ice_num, 
            ice_seq_idx (_type_): _description_

        Returns:
            _type_: _description_
        """
        inputs_embeds = super().forward(img_input, ice_seq_idx)
        if ice_input is None:
            lm_output = self.lm_model(inputs_embeds=inputs_embeds)
            return lm_output

        bs, ice_num, ice_seq_len = ice_input['input_ids'].shape

        ice_input['input_ids'] = ice_input['input_ids'].view(-1, ice_seq_len)
        ice_input['attention_mask'] = ice_input['attention_mask'].view(-1, ice_seq_len)
        ice_features = self.sen_model(
            input_ids=ice_input['input_ids'],
            attention_mask=ice_input['attention_mask'],
        )['text_embeds']
        ice_features = ice_features.view(bs, ice_num, -1)
        inputs_embeds[:, 2 : 2 + ice_num] += ice_features

        output = self.lm_model(inputs_embeds=inputs_embeds, labels=ice_seq_idx)
        return output

    @torch.inference_mode()
    def generation(
        self,
        img_input,
        shot_num,
        coco_ds,
        processor,
        text_field,
        repetition_penalty=2.0,
    ):
        """
        Generate for one batch
        """
        ice_input = None
        device = next(self.lm_model.parameters()).device
        ice_seq_idx = torch.tensor([[118288, 118289]]).to(device)

        for _ in range(shot_num):
            out = self.forward(img_input, ice_input, ice_seq_idx).logits[:, -1, :]
            # set the sp token prob to 0
            out[:, 118287:] = -torch.inf
            for ice_idx in ice_seq_idx:
                out[:, ice_idx] /= repetition_penalty

            next_token_idx = torch.softmax(out, dim=-1).argmax(dim=-1)

            ice_seq_idx = torch.cat(
                [ice_seq_idx, torch.tensor([[next_token_idx]], device=device)],
                dim=1,
            )

            ice_text_list = [ 
                coco_ds[i][text_field] for i in ice_seq_idx.tolist()[0][2:]
            ]
            ice_input = processor(
                text=ice_text_list, padding=True, return_tensors='pt'
            ).to(device) # shape: ice_num * seq_len
            ice_input = {k: v.unsqueeze(dim=0) for k, v in ice_input.items()}

        return ice_seq_idx.detach().cpu().tolist()