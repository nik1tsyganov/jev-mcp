from common_worker import main, model_directory, normalize, questions, limit, serialize, Rejected


class Runtime:
    def __init__(self, config):
        self.model_dir = model_directory(config)
        import torch
        from decider.infer import Decider
        self.torch = torch
        self.device = config.get('device', 'mps')
        if self.device not in ('mps', 'cpu') or self.device == 'mps' and not torch.backends.mps.is_available():
            raise Rejected('transport', {'message': 'requested device unavailable', 'device': self.device})
        torch.set_num_threads(int(config.get('threads', 2)))
        dtype = torch.float32 if self.device == 'cpu' else torch.float16
        self.model = Decider(str(self.model_dir), device=self.device, dtype=dtype, use_graphs=False)
        if self.model.name != 'decider-2b-v11':
            raise Rejected('transport', {'message': 'unexpected Decider model name', 'name': self.model.name})
        self.model.m.lm.config.use_cache = False
        self.maximum = min(int(config.get('max_input_tokens', 4096)), 32768,
                           self.model.m.lm.config.max_position_embeddings)
        self.info = {'device': self.device, 'dtype': str(dtype), 'max_input_tokens': self.maximum,
                     'limit_source': 'config.max_input_tokens (default pilot evaluation-protocol.json: 4096), capped at model card 32768',
                     'layout': 'state_first', 'independent': True, 'use_graphs': False}

    def classify(self, request):
        qs = questions(request)
        state = serialize(request['state'])
        # The measured context length prevents the library's max_state_tokens slice from dropping any token.
        context_tokens = len(self.model.m.tok.encode('Context:\n' + state, add_special_tokens=False))
        prepared = {}
        for qid, q in qs.items():
            _, _, items = self.model._system_one_items(
                state, {qid: q}, True, max(1, context_tokens), 'state_first', self.model.isolated_levels)
            counts = [len(item['ids']) for item in items]
            if not counts:
                raise Rejected('malformed', {'message': 'Decider produced no input rows', 'qid': qid})
            for count in counts:
                limit(count, self.maximum, self.info['limit_source'], qid=qid)
            prepared[qid] = counts
        answers, raw = {}, {}
        input_tokens, output_tokens = 0, 0
        for qid, q in qs.items():
            with self.torch.inference_mode():
                result = self.model.system_one(state, {qid: q}, independent=True,
                                               max_state_tokens=max(1, context_tokens), max_fwd_tokens=1,
                                               layout='state_first')
            raw[qid] = {'result': result, 'complete_input_tokens': prepared[qid]}
            answers[qid] = result['answers'][qid]
            input_tokens += sum(prepared[qid])
            output_tokens += result['usage']['output_tokens']
        if self.device == 'mps':
            self.torch.mps.synchronize()
        try:
            normalized = normalize(answers, qs)
        except Rejected as exc:
            exc.raw['worker_results'] = raw
            exc.input_tokens = input_tokens
            raise
        return normalized, raw, {'input_tokens': input_tokens, 'output_tokens': output_tokens}


if __name__ == '__main__':
    main(Runtime)
