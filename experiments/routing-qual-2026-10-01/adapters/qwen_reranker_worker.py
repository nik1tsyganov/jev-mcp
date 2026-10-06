from common_worker import main, model_directory, normalize, questions, limit, serialize, Rejected

PREFIX = ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. '
          'Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


class Runtime:
    def __init__(self, config):
        self.model_dir = model_directory(config)
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        self.torch = torch
        self.device = config.get('device', 'mps')
        if self.device not in ('mps', 'cpu') or self.device == 'mps' and not torch.backends.mps.is_available():
            raise Rejected('transport', {'message': 'requested device unavailable', 'device': self.device})
        torch.set_num_threads(int(config.get('threads', 2)))
        self.tok = AutoTokenizer.from_pretrained(str(self.model_dir), local_files_only=True,
                                                trust_remote_code=False, padding_side='left')
        dtype = torch.float32 if self.device == 'cpu' else torch.float16
        self.model = AutoModelForCausalLM.from_pretrained(
            str(self.model_dir), local_files_only=True, trust_remote_code=False, use_safetensors=True,
            dtype=dtype, attn_implementation='sdpa').to(self.device).eval()
        self.maximum = min(int(config.get('max_input_tokens', 4096)), self.model.config.max_position_embeddings, 32768)
        self.ids = [self.tok.convert_tokens_to_ids('no'), self.tok.convert_tokens_to_ids('yes')]
        if any(i is None or i == self.tok.unk_token_id for i in self.ids) or self.ids[0] == self.ids[1]:
            raise Rejected('malformed', {'message': 'yes/no tokens missing'})
        self.info = {'device': self.device, 'dtype': str(dtype), 'max_input_tokens': self.maximum,
                     'limit_source': 'config.max_input_tokens (default pilot evaluation-protocol.json: 4096), capped at model card 32768 and config.max_position_embeddings'}

    def classify(self, request):
        qs = questions(request)
        rows = []
        for qid, q in qs.items():
            query = serialize(request['state']) + '\n' + q['instructions']
            for label, criterion in q['criteria'].items():
                prompt = PREFIX + '<Instruct>: ' + q['instructions'] + '\n<Query>: ' + query
                prompt += '\n<Document>: ' + label + ': ' + criterion + SUFFIX
                tokens = self.tok(prompt, add_special_tokens=False, return_tensors='pt', truncation=False)
                count = tokens['input_ids'].shape[1]
                limit(count, self.maximum, self.info['limit_source'], qid=qid, label=label)
                rows.append((qid, label, tokens, count))
        scores = {qid: {} for qid in qs}
        raw = {qid: {} for qid in qs}
        for qid, label, tokens, count in rows:
            with self.torch.inference_mode():
                tokens = {k: v.to(self.device) for k, v in tokens.items()}
                logits = self.model(**tokens, use_cache=False, logits_to_keep=1).logits[0, -1, self.ids].float()
                if not self.torch.isfinite(logits).all():
                    raise Rejected('malformed', {'message': 'nonfinite reranker logits', 'qid': qid, 'label': label})
                values = logits.cpu().tolist()
                yes = self.torch.softmax(logits, dim=-1).cpu().tolist()[1]
            # logit(yes-probability) equals yes-logit minus no-logit, without saturation loss.
            scores[qid][label] = values[1] - values[0]
            raw[qid][label] = {'logits': values, 'yes_probability': yes,
                               'yes_log_odds': scores[qid][label], 'input_tokens': count}
        answers = {}
        for qid, values in scores.items():
            p = self.torch.softmax(self.torch.tensor(list(values.values()), dtype=self.torch.float64), dim=-1).tolist()
            answers[qid] = {'probs': dict(zip(values, p))}
        if self.device == 'mps':
            self.torch.mps.synchronize()
        return normalize(answers, qs), raw, {'input_tokens': sum(row[3] for row in rows), 'output_tokens': 0}


if __name__ == '__main__':
    main(Runtime)
