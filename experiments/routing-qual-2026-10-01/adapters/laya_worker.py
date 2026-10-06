"""Laya inference with a complete prompt; no library truncation path is used."""
from common_worker import main, model_directory, normalize, questions, limit, serialize, Rejected


class Runtime:
    def __init__(self, config):
        self.model_dir = model_directory(config)
        import laya_mlx
        from laya_mlx.agent import collate_items
        from laya_mlx.common import temp_bucket
        self.collate, self.bucket = collate_items, temp_bucket
        if config.get('device', 'gpu') != 'gpu':
            raise Rejected('transport', {'message': 'pinned Laya invocation requires gpu'})
        self.agent = laya_mlx.load(str(self.model_dir), device='gpu', dtype='float16')
        self.maximum = min(int(config.get('max_input_tokens', self.agent.cfg['max_len'])), self.agent.cfg['max_len'])
        self.head = self.agent.cfg['head_max_len']
        self.info = {'device': 'gpu', 'dtype': 'float16', 'max_input_tokens': self.maximum,
                     'head_max_len': self.head, 'option_token_limit': 48,
                     'limit_source': 'rl_agent_config.json: max_len/head_max_len; laya_mlx.common.build_prefix: 48',
                     'input_encoding': 'complete JSON state; complete per-question choice prefix'}

    def classify(self, request):
        import numpy as np
        import mlx.core as mx
        qs = questions(request)
        tok = self.agent.tok
        encode = lambda text: tok(text, add_special_tokens=False)['input_ids']
        state = encode(serialize(request['state']))
        request_count = len(encode(serialize(request)))
        items, details = [], {}
        for qid, q in qs.items():
            head = encode('choice question: ' + q['instructions'])
            options = []
            for label, criterion in q['criteria'].items():
                option = encode(' ' + label + (': ' + criterion if criterion else ''))
                limit(len(option), 48, 'laya_mlx.common.build_prefix option cap', qid=qid, label=label,
                      serialized_request_tokens=request_count)
                options.append([tok.mask_token_id] + option)
            head_count = len(head) + sum(map(len, options))
            limit(head_count, self.head, 'rl_agent_config.json: head_max_len', qid=qid,
                  serialized_request_tokens=request_count)
            ids = [tok.cls_token_id] + head + [tok.sep_token_id]
            markers = []
            for option in options:
                markers.append(len(ids))
                ids.extend(option)
            ids += [tok.sep_token_id] + state + [tok.sep_token_id]
            limit(len(ids), self.maximum, 'rl_agent_config.json: max_len (or smaller configured max_input_tokens)',
                  qid=qid, serialized_request_tokens=request_count)
            items.append({'ids': ids, 'markers': markers, 'qtype': 0})
            details[qid] = {'input_tokens': len(ids), 'head_tokens': head_count}
        answers, outputs = {}, {}
        for (qid, q), item in zip(qs.items(), items):
            # No max_length argument: preflight rejects overflow, and collation cannot cut input.
            batch = self.collate([item], tok.pad_token_id)
            logits, action = self.agent.forward(batch)
            values = np.asarray(logits)[0, :len(item['markers'])]
            if not np.isfinite(values).all():
                raise Rejected('malformed', {'message': 'nonfinite Laya logits', 'qid': qid})
            scale = self.agent.temperature_by_options.get(self.bucket(0, len(values)), self.agent.temperature[0])
            z = values / max(1e-3, float(scale))
            p = np.exp(z - z.max())
            p /= p.sum()
            answers[qid] = {'probs': {label: float(value) for label, value in zip(q['criteria'], p)}}
            outputs[qid] = {'logits': values.tolist(), 'temperature': float(scale), 'action': np.asarray(action).tolist()}
        mx.synchronize()
        usage = {'input_tokens': sum(len(item['ids']) for item in items), 'output_tokens': 0}
        raw = {'outputs': outputs, 'token_counts': details, 'serialized_request_tokens': request_count,
               'limits': self.info}
        return normalize(answers, qs), raw, usage


if __name__ == '__main__':
    main(Runtime)
