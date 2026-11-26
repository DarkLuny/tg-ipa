#import "PluginInvocation.h"

@interface PluginInvocation () {
    NSInvocation *_invocation;
}
@end

@implementation PluginInvocation

+ (instancetype)invocationWithObject:(id)object {
    return [[[self alloc] initWithInvocation:(NSInvocation *)object] autorelease];
}

- (instancetype)initWithInvocation:(NSInvocation *)invocation {
    self = [super init];
    if (self) {
        _invocation = invocation;
    }
    return self;
}

- (SEL)selector {
    return self.invocation.selector;
}

- (NSMethodSignature *)methodSignature {
    return self.invocation.methodSignature;
}

- (id)rawInvocation {
    return self.invocation;
}

- (void)getArgument:(void *)buffer atIndex:(NSInteger)index {
    [self.invocation getArgument:buffer atIndex:index];
}

- (void)setReturnValue:(void *)buffer {
    [self.invocation setReturnValue:buffer];
}

- (void)getReturnValue:(void *)buffer {
    [self.invocation getReturnValue:buffer];
}

- (void)invoke {
    [self.invocation invoke];
}

@end
