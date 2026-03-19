def handle(command, args):
    """
    主处理函数，用于响应不同的触发词。
    
    参数:
        command (str): 触发的命令名称。
        args (list): 命令附带的参数列表。
    
    返回:
        str: 要显示或由 Claw 朗读的响应内容。
    """
    if command == "小灯胜算":
        return "哎，小灯胜算来了～～～"
    elif command == "保存":
        return "给你存上了皇上"
    else:
        return "没有匹配的命令，请尝试其他指令。"